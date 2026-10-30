<script lang="ts">
  import type { NotifyClient } from '../../account/notify';
  import { notifyCopy, notifyFormat } from '../../copy-notify';

  interface Props {
    /** The school just saved. */
    school: string;
    client: NotifyClient;
    /** Closes the offer; `later`: the person said not now. */
    onclose: (later: boolean) => void;
  }

  let { school, client, onclose }: Props = $props();
  let busy = $state(false);

  async function turnOn(): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      // The browser asks for permission here, because the person pressed the button.
      await client.turnOn();
    } catch {
      // Settings > Notifications says how it stands.
    } finally {
      busy = false;
      onclose(false);
    }
  }
</script>

<!-- After a school is saved, while this browser gets no notifications: one offer, never a prompt on load. -->
<div class="offer" role="status" data-testid="notify-offer">
  <p>{notifyFormat.offer(school)}</p>
  <div class="actions">
    <button class="primary" type="button" disabled={busy} onclick={turnOn}>
      {notifyCopy.offer.turnOn}
    </button>
    <button
      class="link"
      type="button"
      onclick={() => {
        onclose(true);
      }}
    >
      {notifyCopy.offer.later}
    </button>
  </div>
</div>

<style>
  .offer {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    z-index: 12;
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: min(300px, calc(100vw - 32px));
    padding: 14px;
    color: var(--text-1);
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 12px;
    box-shadow: 0 12px 32px rgb(var(--shadow) / 0.5);
  }

  p {
    margin: 0;
    font-size: 14px;
    line-height: 20px;
  }

  .actions {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  button.primary {
    height: 36px;
    padding: 0 14px;
    font: inherit;
    font-size: 13px;
    font-weight: 600;
    color: var(--bg);
    cursor: pointer;
    background: var(--text-1);
    border: 0;
    border-radius: 10px;
  }

  button.link {
    padding: 4px 8px;
    font: inherit;
    font-size: 13px;
    color: var(--text-2);
    cursor: pointer;
    background: none;
    border: 0;
  }

  button:disabled {
    cursor: default;
    opacity: 0.6;
  }

  button:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }
</style>
