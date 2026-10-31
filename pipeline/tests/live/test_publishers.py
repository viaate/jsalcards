"""The publishers: key checks (T15b), SigV4 (T21), a folder, a bucket and a GitHub repo.

The bucket and the repository are local stubs (httpx.MockTransport); every body is SYNTHETIC.
"""

import base64
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from snowlight.live.publish import holds
from snowlight.live.publishers import (
    CACHE_CONTROL,
    CONTENT_TYPE,
    Credentials,
    DirPublisher,
    GitHubPublisher,
    GuardRefusedError,
    HostRefusedError,
    KeyRefusedError,
    MovedError,
    PublishError,
    R2Publisher,
    WriteGuard,
    blob_etag,
    canonical_request,
    check_key,
    host_refused_until,
    refusal_of,
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
        self.messages: list[str] = []

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
            self.messages.append(str(body["message"]))
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


def test_a_commit_message_is_one_writes_and_never_sticks_to_the_next() -> None:
    """A pass's counts-only message names its own commit only: a later write (an alerts file,
    say) gets the default, which names the Actions run that made it."""
    from snowlight.live import cli as live_cli  # noqa: PLC0415
    from snowlight.live.publish import emergency_blank, release  # noqa: PLC0415

    repo = Repo()
    config = live_cli.LiveConfig(
        host={"kind": "github", "repository": "viaate/snowlight-synthetic"},
        state={},
        site="",
        site_repository="",
    )
    env = {"LIVE_HOST_TOKEN": "synthetic", "GITHUB_RUN_ID": "4242", "GITHUB_WORKFLOW": "live-read"}
    host = live_cli.make_host(config, env, httpx.Client(transport=httpx.MockTransport(repo)))
    assert isinstance(host, GitHubPublisher)
    host.api = "https://api.synthetic.example"
    host.message = "live v1-shadow pass 2026-11-17T11:05:00Z run 4242 sweep 70"
    host.write({"v1-shadow/live/closings.json": b"{}"})
    host.write({"v1-shadow/live/alerts.json": b"{}"})
    assert repo.messages == [
        "live v1-shadow pass 2026-11-17T11:05:00Z run 4242 sweep 70",
        "Publish the live files (live-read run 4242)",
    ]
    now = datetime(2026, 11, 17, 11, 5, tzinfo=UTC)
    emergency_blank(host, now, ("v1-shadow",))
    release(host, now, ("v1-shadow",))
    assert repo.messages[2:] == [
        "live-blank v1-shadow hold 2026-11-17T11:05:00Z",
        "live-blank v1-shadow release 2026-11-17T11:05:00Z",
    ]  # nothing was lit, so nothing was blanked
    # no run named outside Actions
    plain = live_cli.make_host(config, {"LIVE_HOST_TOKEN": "synthetic"}, httpx.Client())
    assert isinstance(plain, GitHubPublisher)
    assert plain.default_message == "Publish the live files"


# --- live-403: GitHub's reason, the wait, and fewer calls ---------------------------------------

T0 = datetime(2026, 11, 17, 17, 0, 15, tzinfo=UTC)


def _answer(
    status: int,
    *,
    at: datetime = T0,
    message: str = "SYNTHETIC words",
    **headers: str,
) -> httpx.Response:
    sent = {
        "date": format_datetime(at, usegmt=True),
        **{k.replace("_", "-"): v for k, v in headers.items()},
    }
    return httpx.Response(status, headers=sent, json={"message": message})


def test_github_refusal_of_sets_the_reason_and_until() -> None:
    reset = T0 + timedelta(minutes=26)
    primary = _answer(
        403,
        message="API rate limit exceeded for user ID 1234567.",
        x_ratelimit_limit="5000",
        x_ratelimit_remaining="0",
        x_ratelimit_used="5000",
        x_ratelimit_resource="core",
        x_ratelimit_reset=str(int(reset.timestamp())),
        x_github_request_id="40BC:27D4F6",
    )
    found = refusal_of(primary, T0)
    assert found.reason == "primary_rate_limit"
    assert found.until == reset + timedelta(seconds=1)
    assert found.text() == (
        "primary_rate_limit; 0 of 5000 left, used 5000, core, resets 17:26:15Z; request 40BC:27D4F6"
    )
    # the server's clock 30 s ahead: its reset is moved onto the local clock
    skewed = refusal_of(primary, T0 - timedelta(seconds=30))
    assert skewed.until == reset + timedelta(seconds=1) - timedelta(seconds=30)
    # retry-after counts from the answer's Date
    waited = refusal_of(
        _answer(403, message="You have exceeded a secondary rate limit.", retry_after="90"), T0
    )
    assert (waited.reason, waited.retry_after) == ("secondary_rate_limit", 90.0)
    assert waited.until == T0 + timedelta(seconds=90)
    # a secondary limit that names no wait: 60 s, doubling on each repeat, at most 15 min
    bare = _answer(403, message="You have exceeded a secondary rate limit.")
    first = refusal_of(bare, T0)
    assert first.until == T0 + timedelta(seconds=60)
    second = refusal_of(bare, T0, first)
    assert second.until == T0 + timedelta(seconds=120)
    long = replace(second, backoff=timedelta(minutes=10))
    assert refusal_of(bare, T0, long).until == T0 + timedelta(minutes=15)
    assert refusal_of(_answer(429), T0).until == T0 + timedelta(seconds=60)
    # never under 10 s nor over 61 min after the answer
    assert refusal_of(_answer(429, retry_after="0"), T0).until == T0 + timedelta(seconds=10)
    far = _answer(
        403,
        x_ratelimit_remaining="0",
        x_ratelimit_reset=str(int((T0 + timedelta(hours=3)).timestamp())),
    )
    assert refusal_of(far, T0).until == T0 + timedelta(minutes=61)
    # every other answer: a fixed code and no wait
    for status, message, reason in [
        (401, "Bad credentials", "bad_credentials"),
        (403, "Resource not accessible by personal access token", "no_permission"),
        (403, "SYNTHETIC", "forbidden"),
        (404, "Not Found", "not_found"),
        (409, "SYNTHETIC", "conflict"),
        (422, "SYNTHETIC", "unprocessable"),
        (502, "SYNTHETIC", "server"),
        (418, "SYNTHETIC", "other"),
    ]:
        other = refusal_of(_answer(status, message=message), T0)
        assert (other.reason, other.until) == (reason, None)
    needs = refusal_of(_answer(403, x_accepted_github_permissions="contents=write"), T0)
    assert needs.text() == "forbidden; needs contents=write"


def _clocked(repo: Repo, clock: list[datetime]) -> GitHubPublisher:
    return GitHubPublisher(
        repository="viaate/snowlight-synthetic",
        token="synthetic-token",  # noqa: S106 - a test value
        client=httpx.Client(transport=httpx.MockTransport(repo)),
        api="https://api.synthetic.example",
        now=lambda: clock[0],
    )


class Limited(Repo):
    """:class:`Repo`, refusing every request with GitHub's primary limit until ``reset``."""

    def __init__(self, clock: list[datetime], reset: datetime) -> None:
        super().__init__()
        self.clock, self.reset = clock, reset

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.clock[0] < self.reset:
            path = request.url.path.removeprefix("/repos/viaate/snowlight-synthetic/")
            self.calls.append(f"{request.method} {path}")
            return _answer(
                403,
                at=self.clock[0],
                message="API rate limit exceeded for user ID 1234567.",
                x_ratelimit_limit="5000",
                x_ratelimit_remaining="0",
                x_ratelimit_reset=str(int(self.reset.timestamp())),
            )
        return super().__call__(request)


def test_github_refused_host_sends_nothing_until_allowed() -> None:
    clock = [T0]
    repo = Limited(clock, T0 + timedelta(minutes=26))
    publisher = _clocked(repo, clock)
    with pytest.raises(HostRefusedError, match=r"^read v1/live/closings\.json: HTTP 403 \("):
        publisher.read("v1/live/closings.json")
    until = T0 + timedelta(minutes=26, seconds=1)
    assert publisher.refused_until(T0) == until
    assert host_refused_until(publisher, T0) == until
    assert host_refused_until(DirPublisher(Path("/nonexistent")), T0) is None
    for minutes in (1, 10, 26):
        clock[0] = T0 + timedelta(minutes=minutes)
        with pytest.raises(HostRefusedError) as raised:
            publisher.write({"v1/live/closings.json": b"{}"})
        assert str(raised.value) == (
            "read branch: not sent, host refused until 17:26:16Z (primary_rate_limit)"
        )
        assert raised.value.rate_limited
    assert len(repo.calls) == 1
    clock[0] = until
    publisher.write({"v1/live/closings.json": b"{}"})
    assert repo.tree() == {"v1/live/closings.json": b"{}"}


def test_github_success_after_refusal_clears_it_and_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="snowlight")
    clock = [T0]
    repo = Limited(clock, T0 + timedelta(minutes=5))
    publisher = _clocked(repo, clock)
    with pytest.raises(HostRefusedError):
        publisher.read("v1/live/closings.json")
    clock[0] = T0 + timedelta(minutes=6)
    assert publisher.read("v1/live/closings.json") is None
    assert publisher.read("v1/live/closings.json") is None
    assert publisher.refusal is None
    answered = [rec for rec in caplog.records if "answers again" in rec.getMessage()]
    assert [rec.getMessage() for rec in answered] == ["live host answers again after 360 s"]
    assert [rec.levelno for rec in answered] == [logging.INFO]
    warned = [rec for rec in caplog.records if rec.levelno >= logging.WARNING]
    assert len(warned) == 1


def test_github_contents_404_and_moved_422_are_not_warnings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="snowlight")
    repo = Repo()
    publisher = _github(repo)
    assert publisher.read("v1/live/hold.json") is None
    moves = iter(range(100))

    def other_writer() -> None:
        repo.head = repo._sha(f"someone else {next(moves)}")
        repo.commits[repo.head] = next(iter(repo.trees))

    repo.race = other_writer
    with pytest.raises(MovedError):
        publisher.write({"v1/live/closings.json": b"{}"})
    assert not [rec for rec in caplog.records if rec.levelno >= logging.WARNING]
    debug = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.DEBUG]
    assert any("HTTP 404 (not_found" in line for line in debug)
    assert any("HTTP 422 (unprocessable" in line for line in debug)
    assert publisher.refusal is None


def test_github_error_text_keeps_its_prefix_and_never_the_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="snowlight")

    def failing(_request: httpx.Request) -> httpx.Response:
        return _answer(
            403,
            message="Resource not accessible by SYNTHETIC Alpha token",
            x_github_request_id="SYNT:1",
            x_accepted_github_permissions="contents=write",
        )

    publisher = GitHubPublisher(
        repository="viaate/snowlight-synthetic",
        token="synthetic-secret-token",  # noqa: S106 - a test value
        client=httpx.Client(transport=httpx.MockTransport(failing)),
        api="https://api.synthetic.example",
    )
    with pytest.raises(HostRefusedError) as raised:
        publisher.read("v1/live/closings.json")
    assert str(raised.value) == (
        "read v1/live/closings.json: HTTP 403 (no_permission; needs contents=write; request SYNT:1)"
    )
    assert not raised.value.rate_limited
    for text in (str(raised.value), caplog.text):
        assert "SYNTHETIC" not in text
        assert "synthetic-secret-token" not in text
        assert "Bearer" not in text


class Conditional(Repo):
    """:class:`Repo` whose contents reads carry the blob sha as the ETag and answer
    ``If-None-Match`` with 304, and honour ``?ref=<sha>``."""

    def __init__(self) -> None:
        super().__init__()
        self.conditional: list[str | None] = []
        self.lagging: set[str] = set()
        """Commits GitHub's replica does not know yet (a read at one answers 404)."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/repos/viaate/snowlight-synthetic/")
        if request.method != "GET" or not path.startswith("contents/"):
            return super().__call__(request)
        self.calls.append(f"GET {path}@{request.url.params.get('ref')}")
        self.conditional.append(request.headers.get("if-none-match"))
        ref = request.url.params.get("ref", "main")
        if ref in self.lagging:
            return httpx.Response(404, json={"message": f"No commit found for the ref {ref}"})
        files = self.trees[self.commits[self.head if ref == "main" else ref]]
        key = path.removeprefix("contents/")
        if key not in files:
            return httpx.Response(404)
        body = files[key]
        etag = (
            '"'
            + hashlib.sha1(b"blob %d\0" % len(body) + body, usedforsecurity=False).hexdigest()
            + '"'
        )
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"etag": etag})
        return httpx.Response(200, headers={"etag": etag}, content=body)


def test_github_conditional_read_sends_if_none_match_and_a_304_returns_the_kept_bytes() -> None:
    repo = Conditional()
    other = _github(repo)
    other.write({"v1/live/opens.json": b'{"SYNTHETIC":1}'})
    publisher = _github(repo)
    assert publisher.read("v1/live/opens.json") == b'{"SYNTHETIC":1}'
    assert publisher.read("v1/live/opens.json") == b'{"SYNTHETIC":1}'
    assert repo.conditional[-2] is None
    assert repo.conditional[-1] == blob_etag(b'{"SYNTHETIC":1}')
    assert repo.calls[-2:] == ["GET contents/v1/live/opens.json@main"] * 2
    other.write({"v1/live/opens.json": b'{"SYNTHETIC":2}'})
    assert publisher.read("v1/live/opens.json") == b'{"SYNTHETIC":2}'


def test_github_written_files_are_seeded_with_their_blob_sha() -> None:
    repo = Conditional()
    publisher = _github(repo)
    body = b'{"SYNTHETIC":"closings"}'
    publisher.write({"v1/live/closings.json": body})
    assert publisher.read("v1/live/closings.json") == body
    assert repo.conditional == [blob_etag(body)]  # answered 304: the read cost nothing
    assert blob_etag(b"{}") == '"9e26dfeeb6e641a33dae4961196235bdb965b21b"'  # git hash-object


def test_github_a_read_at_a_sha_is_never_sent_twice() -> None:
    repo = Conditional()
    publisher = _github(repo)
    publisher.write({"v1/live/closings.json": b"{}"})
    head = repo.head
    for _ in range(3):
        assert publisher._read_at("v1/live/closings.json", head) == b"{}"
        assert publisher._read_at("v1/live/hold.json", head) is None
    assert repo.calls.count(f"GET contents/v1/live/closings.json@{head}") == 1
    assert repo.calls.count(f"GET contents/v1/live/hold.json@{head}") == 1
    # only the last 16 shas are kept
    for index in range(16):
        publisher.write({"v1/live/closings.json": f'{{"n":{index}}}'.encode()})
        publisher._read_at("v1/live/hold.json", repo.head)
    publisher._read_at("v1/live/hold.json", head)
    assert repo.calls.count(f"GET contents/v1/live/hold.json@{head}") == 2


HOLD_GUARD = WriteGuard("v1/live/hold.json", holds)
HELD = (
    b'{"schema_version":1,"held":true,"at":"2026-11-17T17:00:00Z","held_at":"2026-11-17T17:00:00Z"}'
)


def test_github_commit_on_own_head_makes_get_ref_and_three_writes_only() -> None:
    repo = Conditional()
    publisher = _github(repo)
    publisher.write_guarded({"v1/live/closings.json": b'{"a":1}'}, HOLD_GUARD)
    repo.calls.clear()
    publisher.write_guarded({"v1/live/closings.json": b'{"a":2}'}, HOLD_GUARD)
    assert repo.calls == [
        "GET git/ref/heads/main",
        "POST git/trees",
        "POST git/commits",
        "PATCH git/refs/heads/main",
    ]
    assert repo.tree() == {"v1/live/closings.json": b'{"a":2}'}


def test_github_commit_after_another_writer_takes_the_full_path_and_its_hold_refuses() -> None:
    repo = Conditional()
    publisher = _github(repo)
    publisher.write_guarded({"v1/live/closings.json": b'{"a":1}'}, HOLD_GUARD)
    _github(repo).write({"v1/predictions/latest.json": b'{"p":1}'})  # predict.yml
    repo.calls.clear()
    publisher.write_guarded({"v1/live/closings.json": b'{"a":2}'}, HOLD_GUARD)
    head = repo.parents[repo.head][0]
    assert repo.calls == [
        "GET git/ref/heads/main",
        f"GET contents/v1/live/hold.json@{head}",
        f"GET git/commits/{head}",
        "POST git/trees",
        "POST git/commits",
        "PATCH git/refs/heads/main",
    ]
    # live blank's hold lands with the other writer's next commit: the guard refuses
    held = HELD
    blank = _github(repo)
    blank.write({"v1/live/hold.json": held})
    repo.calls.clear()
    with pytest.raises(GuardRefusedError):
        publisher.write_guarded({"v1/live/closings.json": b'{"a":3}'}, HOLD_GUARD)
    assert not [call for call in repo.calls if call.startswith(("POST", "PATCH"))]
    assert repo.tree()["v1/live/closings.json"] == b'{"a":2}'


def test_github_live_blank_between_get_ref_and_patch_is_still_refused() -> None:
    repo = Conditional()
    publisher = _github(repo)
    publisher.write_guarded({"v1/live/closings.json": b'{"a":1}'}, HOLD_GUARD)
    held = HELD

    def live_blank() -> None:
        repo.race = None
        _github(repo).write({"v1/live/hold.json": held, "v1/live/closings.json": b"{}"})

    repo.race = live_blank  # lands after this write's GET ref, before its PATCH
    with pytest.raises(GuardRefusedError):
        publisher.write_guarded({"v1/live/closings.json": b'{"a":2}'}, HOLD_GUARD)
    assert repo.tree() == {"v1/live/hold.json": held, "v1/live/closings.json": b"{}"}


class Slow(Repo):
    """:class:`Repo` whose answers take ``delay`` on the clock, refusing in the way given
    (its ``Date`` is when the answer leaves GitHub: the end of the delay)."""

    def __init__(self, clock: list[datetime], delay: timedelta, refusal: dict[str, str]) -> None:
        super().__init__()
        self.clock, self.delay, self.refusal = clock, delay, refusal

    def __call__(self, _request: httpx.Request) -> httpx.Response:
        self.clock[0] += self.delay
        message = (
            "You have exceeded a secondary rate limit."
            if "retry_after" in self.refusal
            else "API rate limit exceeded for user ID 1234567."
        )
        return _answer(403, at=self.clock[0], message=message, **self.refusal)


@pytest.mark.parametrize("delay", [timedelta(seconds=0.3), timedelta(seconds=2.5)])
def test_github_a_slow_answer_never_shortens_the_wait_it_names(delay: timedelta) -> None:
    """GitHub's wait counts from its answer, not from when the request went out: retry-after
    is waited in full after the answer came, and a primary limit until its reset + 1 s."""
    clock = [T0]
    publisher = _clocked(Slow(clock, delay, {"retry_after": "60"}), clock)
    with pytest.raises(HostRefusedError):
        publisher.read("v1/live/closings.json")
    until = publisher.refused_until(clock[0])
    assert until is not None
    assert until - clock[0] >= timedelta(seconds=60)
    reset = T0 + timedelta(minutes=26)
    clock = [T0]
    primary = {
        "x_ratelimit_limit": "5000",
        "x_ratelimit_remaining": "0",
        "x_ratelimit_reset": str(int(reset.timestamp())),
    }
    publisher = _clocked(Slow(clock, delay, primary), clock)
    with pytest.raises(HostRefusedError):
        publisher.read("v1/live/closings.json")
    until = publisher.refused_until(clock[0])
    assert until is not None
    assert until >= reset + timedelta(seconds=1)


def test_github_abuse_detection_is_a_secondary_rate_limit() -> None:
    """GitHub's older words for a secondary limit (no retry-after, calls left) wait, as a
    secondary limit does, and never take the failed-pass path."""
    older = _answer(
        403,
        message="You have triggered an abuse detection mechanism. Please wait a few minutes.",
        x_ratelimit_remaining="4000",
    )
    found = refusal_of(older, T0)
    assert found.reason == "secondary_rate_limit"
    assert found.until == T0 + timedelta(seconds=60)


def test_github_answers_again_only_after_a_wait(caplog: pytest.LogCaptureFixture) -> None:
    """``answers again`` ends a rate limit; after an error answer that named no wait (a 5xx,
    a plain 403) the line says which answer it follows."""
    caplog.set_level(logging.DEBUG, logger="snowlight")
    repo = Repo()
    failing = [True]

    def transport(request: httpx.Request) -> httpx.Response:
        if failing[0]:
            failing[0] = False
            return _answer(502, message="SYNTHETIC outage")
        return repo(request)

    publisher = GitHubPublisher(
        repository="viaate/snowlight-synthetic",
        token="synthetic-token",  # noqa: S106 - a test value
        client=httpx.Client(transport=httpx.MockTransport(transport)),
        api="https://api.synthetic.example",
        now=lambda: T0,
    )
    with pytest.raises(HostRefusedError):
        publisher.read("v1/live/closings.json")
    assert publisher.refused_until(T0) is None  # no wait: today's rules apply
    assert publisher.read("v1/live/closings.json") is None
    lines = [rec.getMessage() for rec in caplog.records if "live host answers" in rec.getMessage()]
    assert lines == ["live host answers (after HTTP 502, server)"]


def test_github_a_guard_read_at_a_commit_github_does_not_know_yet_is_read_again() -> None:
    """A replica behind a fresh head answers 404 "No commit found" for a read at it: that
    says nothing of the file, so it is not kept and the guard is read again at the next
    head this process makes (``live blank``'s hold is still caught by the commit)."""
    repo = Conditional()
    publisher = _github(repo)
    publisher.write_guarded({"v1/live/closings.json": b'{"a":1}'}, HOLD_GUARD)
    # live blank holds (with the other writer's commit); GitHub's replica lags behind it
    _github(repo).write({"v1/live/hold.json": HELD})
    repo.lagging.add(repo.head)
    publisher.write_guarded({"v1/live/closings.json": b'{"a":2}'}, HOLD_GUARD)
    repo.lagging.clear()
    repo.calls.clear()
    with pytest.raises(GuardRefusedError):
        publisher.write_guarded({"v1/live/closings.json": b'{"a":3}'}, HOLD_GUARD)
    assert f"GET contents/v1/live/hold.json@{repo.head}" in repo.calls
    assert not [call for call in repo.calls if call.startswith(("POST", "PATCH"))]
    # a plain 404 at a commit (no such file) is known there: never asked again
    publisher = _github(repo)
    head = repo.head
    repo.calls.clear()
    assert publisher._read_at("v1/live/none.json", head) is None
    assert publisher._read_at("v1/live/none.json", head) is None
    assert repo.calls == [f"GET contents/v1/live/none.json@{head}"]
