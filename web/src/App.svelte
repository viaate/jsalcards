<script lang="ts">
  import { copy } from './copy';
</script>

<main class="stage">
  <h1 class="visually-hidden">{copy.appName}</h1>
</main>

<style>
  .stage {
    position: fixed;
    inset: 0;
    background: var(--bg);
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
    border: 0;
  }
</style>
