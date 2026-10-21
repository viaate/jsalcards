"""The publishers: key checks (T15b), SigV4 (T21), a folder, a bucket and a GitHub repo.

The bucket and the repository are local stubs (httpx.MockTransport); every body is SYNTHETIC.
"""

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from snowlight.live.publishers import (
    CACHE_CONTROL,
    CONTENT_TYPE,
    Credentials,
    DirPublisher,
    GitHubPublisher,
    KeyRefusedError,
    PublishError,
    R2Publisher,
    canonical_request,
    check_key,
    sign,
    signing_key,
)

EMPTY = hashlib.sha256(b"").hexdigest()
S3_KEYS = Credentials(
    "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1", "s3"
)
S3_TIME = datetime(2013, 5, 24, tzinfo=UTC)
S3_HOST = "examplebucket.s3.amazonaws.com"
SUITE_TIME = datetime(2015, 8, 30, 12, 36, tzinfo=UTC)
SUITE_SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # noqa: S105 - AWS example key


# --- T15b: keys ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "v1/live/closings.json",
        "v1-shadow/live/closings.json",
        "v1/live/days/2027-01-12.json",
        "v1/live/opens.json",
    ],
)
def test_keys_under_v1_and_v1_shadow_are_allowed(key: str) -> None:
    assert check_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        "live/closings.json",
        "/v1/live/closings.json",
        "v2/live/closings.json",
        "v1/../state/ledger.json",
        "v1/live/../../state.json",
        "v1//closings.json",
        "v1/live/closings.txt",
        "v1/live/.hidden.json",
        "v1/live/Closings.json",
        "v1",
        "v1/",
        "state/ledger.sqlite",
        "v1-shadowy/live/closings.json",
        "v1/live/closings.json/",
        "",
    ],
)
def test_keys_outside_v1_are_refused(key: str, tmp_path: Path) -> None:
    with pytest.raises(KeyRefusedError):
        check_key(key)
    with pytest.raises(KeyRefusedError):
        DirPublisher(tmp_path).write({key: b"{}"})
    assert list(tmp_path.iterdir()) == []


def test_one_bad_key_writes_nothing_at_all(tmp_path: Path) -> None:
    with pytest.raises(KeyRefusedError):
        DirPublisher(tmp_path).write({"v1/live/closings.json": b"{}", "state/x.json": b"{}"})
    assert list(tmp_path.iterdir()) == []


# --- the folder ---------------------------------------------------------------------------------


def test_dir_publisher_writes_and_reads_back(tmp_path: Path) -> None:
    publisher = DirPublisher(tmp_path)
    assert publisher.read("v1/live/closings.json") is None
    publisher.write({"v1/live/closings.json": b'{"a":1}', "v1/live/opens.json": b"{}"})
    assert publisher.read("v1/live/closings.json") == b'{"a":1}'
    assert (tmp_path / "v1/live/opens.json").read_bytes() == b"{}"
    assert not any(path.name.endswith(".tmp") for path in tmp_path.rglob("*"))


# --- T21: SigV4 against AWS's published examples -----------------------------------------------


def test_signing_key_matches_the_aws_example() -> None:
    # AWS General Reference, "Examples of how to derive a signing key"
    assert (
        signing_key(SUITE_SECRET, "20120215", "us-east-1", "iam").hex()
        == "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d"
    )


def test_get_vanilla_matches_the_test_suite() -> None:
    keys = Credentials("AKIDEXAMPLE", SUITE_SECRET, "us-east-1", "service")
    headers = {"Host": "example.amazonaws.com", "X-Amz-Date": "20150830T123600Z"}
    request, signed = canonical_request("GET", "/", {}, headers, EMPTY)
    assert request == (
        "GET\n/\n\nhost:example.amazonaws.com\nx-amz-date:20150830T123600Z\n\n"
        f"host;x-amz-date\n{EMPTY}"
    )
    assert signed == "host;x-amz-date"
    assert sign("GET", "/", {}, headers, EMPTY, credentials=keys, now=SUITE_TIME) == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        "SignedHeaders=host;x-amz-date, "
        "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    )


def test_iam_list_users_matches_the_aws_example() -> None:
    keys = Credentials("AKIDEXAMPLE", SUITE_SECRET, "us-east-1", "iam")
    headers = {
        "Host": "iam.amazonaws.com",
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        "X-Amz-Date": "20150830T123600Z",
    }
    query = {"Version": "2010-05-08", "Action": "ListUsers"}
    assert sign("GET", "/", query, headers, EMPTY, credentials=keys, now=SUITE_TIME).endswith(
        "SignedHeaders=content-type;host;x-amz-date, "
        "Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7"
    )


def _s3(method: str, path: str, query: dict[str, str], extra: dict[str, str], body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    headers = {
        "Host": S3_HOST,
        "x-amz-date": "20130524T000000Z",
        "x-amz-content-sha256": digest,
        **extra,
    }
    return sign(method, path, query, headers, digest, credentials=S3_KEYS, now=S3_TIME)


@pytest.mark.parametrize(
    ("method", "path", "query", "extra", "body", "signature"),
    [
        (
            "GET",
            "/test.txt",
            {},
            {"Range": "bytes=0-9"},
            b"",
            "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41",
        ),
        (
            "PUT",
            "/test$file.text",
            {},
            {
                "Date": "Fri, 24 May 2013 00:00:00 GMT",
                "x-amz-storage-class": "REDUCED_REDUNDANCY",
            },
            b"Welcome to Amazon S3.",
            "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd",
        ),
        (
            "GET",
            "/",
            {"lifecycle": ""},
            {},
            b"",
            "fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543",
        ),
        (
            "GET",
            "/",
            {"max-keys": "2", "prefix": "J"},
            {},
            b"",
            "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7",
        ),
    ],
    ids=["get-object", "put-object", "get-lifecycle", "list-objects"],
)
def test_s3_examples_match_the_aws_documentation(  # noqa: PLR0913, PLR0917 - one example
    method: str,
    path: str,
    query: dict[str, str],
    extra: dict[str, str],
    body: bytes,
    signature: str,
) -> None:
    assert _s3(method, path, query, extra, body).endswith(f"Signature={signature}")


# --- the bucket ---------------------------------------------------------------------------------


class Bucket:
    """A SYNTHETIC S3-style bucket: it checks every request's signature as a server would."""

    def __init__(self, keys: Credentials) -> None:
        self.keys = keys
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}
        self.requests: list[httpx.Request] = []
        self.fail: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail is not None:
            return httpx.Response(self.fail)
        body = request.read()
        signed = request.headers["authorization"].split("SignedHeaders=")[1].split(",")[0]
        headers = {name: request.headers[name] for name in signed.split(";")}
        moment = datetime.strptime(request.headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=UTC
        )
        digest = hashlib.sha256(body).hexdigest()
        assert request.headers["x-amz-content-sha256"] == digest
        expected = sign(
            request.method,
            request.url.path,
            {},
            headers,
            digest,
            credentials=self.keys,
            now=moment,
        )
        if request.headers["authorization"] != expected:
            return httpx.Response(403)
        path = request.url.path
        if request.method == "PUT":
            self.objects[path] = (body, dict(request.headers))
            return httpx.Response(200)
        if path in self.objects:
            return httpx.Response(200, content=self.objects[path][0])
        return httpx.Response(404)


KEYS = Credentials("SYNTHETICKEY", "SYNTHETIC/secret", "auto", "s3")
NOW = datetime(2027, 1, 12, 11, 42, 7, tzinfo=UTC)


def _bucket_publisher(bucket: Bucket) -> R2Publisher:
    return R2Publisher(
        endpoint="https://synthetic.r2.example",
        bucket="snowlight-live",
        credentials=KEYS,
        client=httpx.Client(transport=httpx.MockTransport(bucket)),
        now=lambda: NOW,
    )


def test_r2_put_sends_exactly_the_signed_headers_and_reads_back() -> None:
    bucket = Bucket(KEYS)
    publisher = _bucket_publisher(bucket)
    assert publisher.read("v1/live/closings.json") is None
    publisher.write({"v1/live/closings.json": b'{"synthetic":true}'})
    stored, headers = bucket.objects["/snowlight-live/v1/live/closings.json"]
    assert stored == b'{"synthetic":true}'
    sent = {
        name
        for name in headers
        if name not in {"accept", "accept-encoding", "connection", "user-agent", "content-length"}
    }
    assert sent == {
        "host",
        "authorization",
        "cache-control",
        "content-type",
        "x-amz-content-sha256",
        "x-amz-date",
    }
    assert headers["content-type"] == CONTENT_TYPE
    assert headers["cache-control"] == CACHE_CONTROL
    assert headers["x-amz-date"] == "20270112T114207Z"
    assert headers["authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=SYNTHETICKEY/20270112/auto/s3/aws4_request, "
        "SignedHeaders=cache-control;content-type;host;x-amz-content-sha256;x-amz-date, "
    )
    assert publisher.read("v1/live/closings.json") == b'{"synthetic":true}'


def test_r2_refuses_a_bad_key_before_any_request() -> None:
    bucket = Bucket(KEYS)
    with pytest.raises(KeyRefusedError):
        _bucket_publisher(bucket).write({"v1/live/a.json": b"{}", "private/ledger.json": b"{}"})
    assert bucket.requests == []


def test_r2_errors_name_the_key_and_status_only() -> None:
    bucket = Bucket(KEYS)
    bucket.fail = 503
    publisher = _bucket_publisher(bucket)
    with pytest.raises(PublishError, match=r"^put v1/live/closings\.json: HTTP 503$"):
        publisher.write({"v1/live/closings.json": b'{"SYNTHETIC Alpha":1}'})
    with pytest.raises(PublishError, match="HTTP 503"):
        publisher.read("v1/live/closings.json")


def test_r2_wrong_secret_is_refused_by_the_bucket() -> None:
    bucket = Bucket(Credentials("SYNTHETICKEY", "another secret", "auto", "s3"))
    with pytest.raises(PublishError, match="HTTP 403"):
        _bucket_publisher(bucket).write({"v1/live/closings.json": b"{}"})


def test_r2_endpoint_must_be_https() -> None:
    publisher = R2Publisher(
        endpoint="http://synthetic.example",
        bucket="b",
        credentials=KEYS,
        client=httpx.Client(transport=httpx.MockTransport(Bucket(KEYS))),
    )
    with pytest.raises(PublishError, match="HTTPS"):
        publisher.write({"v1/live/closings.json": b"{}"})


def test_credentials_never_show_in_a_repr() -> None:
    assert "SYNTHETIC/secret" not in repr(KEYS)
    assert "SYNTHETICKEY" not in repr(KEYS)


def test_a_transport_failure_is_a_publish_error() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    publisher = R2Publisher(
        endpoint="https://synthetic.r2.example",
        bucket="b",
        credentials=KEYS,
        client=httpx.Client(transport=httpx.MockTransport(broken)),
    )
    with pytest.raises(PublishError, match="ConnectError"):
        publisher.write({"v1/live/closings.json": b"{}"})


# --- the GitHub repository ----------------------------------------------------------------------


class Repo:
    """A SYNTHETIC GitHub repository behind the Git Data and Contents APIs."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.head = self._sha("commit-0")
        self.trees: dict[str, dict[str, bytes]] = {self._sha("tree-0"): {}}
        self.commits: dict[str, str] = {self.head: self._sha("tree-0")}
        self.parents: dict[str, list[str]] = {self.head: []}
        self.calls: list[str] = []
        self.race: Callable[[], None] | None = None
        self.tokens: set[str] = set()

    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()

    def __call__(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - one per route
        path = request.url.path.removeprefix("/repos/viaate/snowlight-synthetic/")
        self.calls.append(f"{request.method} {path}")
        self.tokens.add(request.headers.get("authorization", ""))
        if request.method == "GET" and path == "git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": self.head}})
        if request.method == "GET" and path.startswith("git/commits/"):
            sha = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={"sha": sha, "tree": {"sha": self.commits[sha]}})
        if request.method == "POST" and path == "git/trees":
            body = json.loads(request.read())
            files = dict(self.trees[body["base_tree"]])
            for entry in body["tree"]:
                files[entry["path"]] = entry["content"].encode()
            sha = self._sha(json.dumps(sorted((k, v.decode()) for k, v in files.items())))
            self.trees[sha] = files
            return httpx.Response(201, json={"sha": sha})
        if request.method == "POST" and path == "git/commits":
            body = json.loads(request.read())
            sha = self._sha(f"{body['tree']}{body['parents']}")
            self.commits[sha] = body["tree"]
            self.parents[sha] = list(body["parents"])
            return httpx.Response(201, json={"sha": sha})
        if request.method == "PATCH" and path == "git/refs/heads/main":
            if self.race is not None:
                self.race()
            body = json.loads(request.read())
            new = body["sha"]
            if body["force"] is not False or self.head not in self.parents[new]:
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            self.head = new
            return httpx.Response(200, json={"object": {"sha": new}})
        if request.method == "GET" and path.startswith("contents/"):
            key = path.removeprefix("contents/")
            files = self.trees[self.commits[self.head]]
            if key not in files:
                return httpx.Response(404)
            assert request.headers["accept"] == "application/vnd.github.raw+json"
            return httpx.Response(200, content=files[key])
        return httpx.Response(500)

    def tree(self) -> dict[str, bytes]:
        return self.trees[self.commits[self.head]]


def _github(repo: Repo) -> GitHubPublisher:
    return GitHubPublisher(
        repository="viaate/snowlight-synthetic",
        token="synthetic-token",  # noqa: S106 - a test value
        client=httpx.Client(transport=httpx.MockTransport(repo)),
        api="https://api.synthetic.example",
    )


def test_github_commits_every_file_of_a_publish_in_one_commit() -> None:
    repo = Repo()
    publisher = _github(repo)
    assert publisher.read("v1/live/closings.json") is None
    publisher.write({"v1/live/closings.json": b'{"a":1}', "v1/live/opens.json": b'{"b":2}'})
    assert repo.tree() == {"v1/live/closings.json": b'{"a":1}', "v1/live/opens.json": b'{"b":2}'}
    assert [call for call in repo.calls if call.startswith(("POST", "PATCH"))] == [
        "POST git/trees",
        "POST git/commits",
        "PATCH git/refs/heads/main",
    ]
    assert publisher.read("v1/live/closings.json") == b'{"a":1}'
    assert repo.tokens == {"Bearer synthetic-token"}
    assert "synthetic-token" not in repr(publisher)


def test_github_unchanged_files_make_no_commit() -> None:
    repo = Repo()
    publisher = _github(repo)
    publisher.write({"v1/live/closings.json": b'{"a":1}'})
    head = repo.head
    repo.calls.clear()
    publisher.write({"v1/live/closings.json": b'{"a":1}'})
    assert repo.head == head
    assert "POST git/commits" not in repo.calls


def test_github_never_overwrites_a_second_writer() -> None:
    repo = Repo()
    publisher = _github(repo)
    moves = iter(range(100))

    def other_writer() -> None:
        repo.head = repo._sha(f"someone else {next(moves)}")
        repo.commits[repo.head] = next(iter(repo.trees))

    repo.race = other_writer
    with pytest.raises(PublishError, match="another writer"):
        publisher.write({"v1/live/closings.json": b'{"a":1}'})
    assert repo.head == repo._sha(f"someone else {publisher.attempts - 1}")
    assert repo.calls.count("PATCH git/refs/heads/main") == publisher.attempts


def test_github_builds_again_on_the_other_writers_commit_and_keeps_its_files() -> None:
    """predict.yml and live-ingest.yml both commit to the live repository: a commit that
    lost the race is built again on the new head, with the other writer's files kept."""
    repo = Repo()
    publisher = _github(repo)
    publisher.write({"v1/predictions/latest.json": b'{"p":1}'})
    other = _github(repo)

    def predictions_land() -> None:
        repo.race = None
        other.write({"v1/predictions/latest.json": b'{"p":2}'})

    repo.race = predictions_land
    publisher.write({"v1/live/closings.json": b'{"a":1}'})
    assert repo.tree() == {
        "v1/predictions/latest.json": b'{"p":2}',
        "v1/live/closings.json": b'{"a":1}',
    }
    assert repo.calls.count("PATCH git/refs/heads/main") == 4  # 1 + the other's + 2 of this one


def test_github_refuses_bad_keys_before_any_call() -> None:
    repo = Repo()
    with pytest.raises(KeyRefusedError):
        _github(repo).write({"README.md": b"x"})
    assert repo.calls == []


@pytest.mark.parametrize(
    ("route", "status"),
    [("git/ref/heads/main", 401), ("git/trees", 500), ("contents/", 502)],
)
def test_github_errors_name_the_step_and_status(route: str, status: int) -> None:
    repo = Repo()

    def failing(request: httpx.Request) -> httpx.Response:
        if route in request.url.path:
            return httpx.Response(status, json={"message": "SYNTHETIC Alpha"})
        return repo(request)

    publisher = GitHubPublisher(
        repository="viaate/snowlight-synthetic",
        token="t",  # noqa: S106 - a test value
        client=httpx.Client(transport=httpx.MockTransport(failing)),
        api="https://api.synthetic.example",
    )

    def act() -> None:
        if route == "contents/":
            publisher.read("v1/live/closings.json")
        else:
            publisher.write({"v1/live/closings.json": b"{}"})

    with pytest.raises(PublishError) as raised:
        act()
    assert str(status) in str(raised.value)
    assert "SYNTHETIC" not in str(raised.value)


def test_github_malformed_answers_are_publish_errors() -> None:
    def odd(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "not-a-sha"}})
        return httpx.Response(200, content=b"[]")

    publisher = GitHubPublisher(
        repository="viaate/snowlight-synthetic",
        token="t",  # noqa: S106 - a test value
        client=httpx.Client(transport=httpx.MockTransport(odd)),
    )
    with pytest.raises(PublishError, match="no commit or tree id"):
        publisher.write({"v1/live/closings.json": b"{}"})


def test_github_refuses_bytes_that_are_not_text() -> None:
    with pytest.raises(PublishError, match="UTF-8"):
        _github(Repo()).write({"v1/live/closings.json": base64.b64decode("//79")})
