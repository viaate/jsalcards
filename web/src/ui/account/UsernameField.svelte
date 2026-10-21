<script lang="ts">
  import { onDestroy } from 'svelte';

  // The same rules the Worker applies (format, reserved names and the blocklist), shared.
  import { checkUsername } from '../../../../api/src/usernames/check.ts';
  import type { AccountStore } from '../../account/session';
  import { accountCopy, type AccountErrorCode } from '../../copy-account';

  interface Props {
    store: AccountStore;
    value?: string;
  }

  let { store, value = $bindable('') }: Props = $props();

  /** What the field says under it: a hint, checking, free, or what is wrong. */
  let verdict = $state<'idle' | 'checking' | 'free' | AccountErrorCode>('idle');
  let timer: ReturnType<typeof setTimeout> | undefined;
  let round = 0;

  function known(code: string): AccountErrorCode {
    return code in accountCopy.errors ? (code as AccountErrorCode) : 'server';
  }

  /** The format and the lists here at once; whether it is free, from the API a moment later. */
  function onInput(): void {
    clearTimeout(timer);
    const mine = ++round;
    const name = value.trim();
    if (name.length === 0) {
      verdict = 'idle';
      return;
    }
    const here = checkUsername(name);
    if (here !== null) {
      verdict = known(here.problem);
      return;
    }
    verdict = 'checking';
    timer = setTimeout(() => {
      store.checkUsername(name).then(
        (answer) => {
          if (mine === round) verdict = answer.ok ? 'free' : known(answer.problem);
        },
        () => {
          if (mine === round) verdict = 'idle';
        },
      );
    }, 300);
  }

  onDestroy(() => {
    clearTimeout(timer);
  });

  const bad = $derived(verdict !== 'idle' && verdict !== 'checking' && verdict !== 'free');
  const note = $derived(
    verdict === 'idle'
      ? accountCopy.sheet.usernameHint
      : verdict === 'checking'
        ? accountCopy.sheet.checking
        : verdict === 'free'
          ? accountCopy.sheet.usernameFree
          : accountCopy.errors[verdict],
  );
</script>

<label>
  <span>{accountCopy.sheet.username}</span>
  <input
    bind:value
    oninput={onInput}
    autocomplete="username"
    autocapitalize="none"
    spellcheck="false"
    minlength="3"
    maxlength="20"
    required
    aria-describedby="username-note"
    aria-invalid={bad}
  />
</label>
<small id="username-note" class:bad aria-live="polite">{note}</small>

<style>
  label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    color: var(--text-2);
  }

  input {
    height: 40px;
    padding: 0 12px;
    font: inherit;
    font-size: 15px;
    color: var(--text-1);
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 10px;
  }

  input:focus-visible {
    border-color: var(--text-3);
    outline: 1px solid var(--text-2);
    outline-offset: 1px;
  }

  small {
    margin: 0;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-2);
  }

  small.bad {
    color: var(--status-delayed);
  }

  @media (max-width: 719px) {
    input {
      height: 44px;
      font-size: 16px;
    }
  }
</style>
