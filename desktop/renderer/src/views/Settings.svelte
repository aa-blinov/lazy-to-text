<script>
  import { onMount, onDestroy } from 'svelte';
  import {
    PageHeader, Notice, Button, Switch, Select, FieldControl, Skeleton, IconButton
  } from '@monos/ui';
  import { toast } from '../lib/toast.js';
  import { RefreshCw } from 'lucide-svelte';
  import { t, translateRuntime } from '../lib/i18n.js';
  import { fmt } from '../lib/hotkey.js';
  import { aboutRequested } from '../lib/nav.js';
  import {
    settings, permissions, micTest, devices,
    loadSettings, saveValue, listDevices, refreshDevices, selectDevice, startMicTest,
    refreshPermissions, requestPermission, watchSettingsEvents,
  } from '../lib/settings.js';
  import SettingsSection from '../components/settings/SettingsSection.svelte';
  import SettingRow from '../components/settings/SettingRow.svelte';
  import PermissionBanner from '../components/settings/PermissionBanner.svelte';
  import MicTest from '../components/settings/MicTest.svelte';
  import HotkeysCard from '../components/settings/HotkeysCard.svelte';
  import PalettePicker from '../components/settings/PalettePicker.svelte';
  import AboutDialog from '../components/settings/AboutDialog.svelte';
  import SoundSet from '../components/settings/SoundSet.svelte';
  import { loadSounds } from '../lib/sounds.js';

  let loadError = '';
  let aboutOpen = false;
  // The menu's About entry (Windows, Linux) opens the dialog; a count already
  // there when this screen appears is an old request and is not replayed.
  let aboutSeen = $aboutRequested;
  $: if ($aboutRequested !== aboutSeen) {
    aboutSeen = $aboutRequested;
    aboutOpen = true;
  }
  let scroller;
  let activeSection = 'settings-audio';
  let stopEvents = () => {};
  let observer = null;

  // Mirrors of the stored values the switches bind to; each is reset from
  // the store when a write fails so the control never shows a lie.
  let vad = false;
  let mute = false;
  let autoPaste = false;
  let startAtLogin = false;
  let feedback = true;
  let maxDuration = '300';

  $: s = $settings;
  $: if (s) syncFromStore(s);

  function syncFromStore(value) {
    vad = value.audio.vad_enabled;
    mute = value.audio.mute_output_on_record;
    autoPaste = value.clipboard.auto_paste;
    startAtLogin = Boolean(value.ui?.start_at_login);
    feedback = value.audio_feedback.enabled;
    maxDuration = String(value.audio.max_duration);
  }

  const SECTIONS = [
    { id: 'settings-audio', label: 'Audio input' },
    { id: 'settings-hotkeys', label: 'Hotkeys' },
    { id: 'settings-clipboard', label: 'Clipboard' },
    { id: 'settings-appearance', label: 'Appearance' },
    { id: 'settings-startup', label: 'Startup' },
  ];

  async function load() {
    try {
      await loadSettings();
      // Opening Settings is when someone looks for a microphone that came or went.
      await listDevices({ refresh: true });
      await loadSounds().catch(() => {});
      loadError = '';
    } catch (err) {
      loadError = err.message;
    }
  }

  async function save(key, value, revert) {
    try {
      const result = await saveValue(key, value);
      if (result.save_error) {
        // Applied for now, gone at the next launch: the user has to know.
        toast({ title: $t('Not saved to disk'), description: translateRuntime(result.save_error), tone: 'danger', duration: 0 });
      } else if (result.live_error) {
        toast({ title: $t('Saved, but not applied yet'), description: translateRuntime(result.live_error), tone: 'warning', duration: 6000 });
      } else if (!key.startsWith('ui.')) {
        toast({ title: $t('Saved'), tone: 'success', duration: 1500 });
      }
    } catch (err) {
      revert?.();
      toast({ title: $t('Could not save'), description: err.message, tone: 'danger', duration: 0 });
    }
  }

  async function onDevice(event) {
    const raw = event.detail.value;
    const index = raw === 'default' ? null : Number(raw);
    try {
      await selectDevice(index);
      toast({ title: $t('Saved'), tone: 'success', duration: 1500 });
    } catch (err) {
      toast({ title: $t('Could not switch the microphone'), description: err.message, tone: 'danger', duration: 0 });
      await listDevices({ refresh: true });
    }
  }

  async function onTest() {
    try {
      await startMicTest();
    } catch {
      // The store already holds the reason; the notice under the button shows it.
    }
  }

  async function onPermission(event) {
    const { kind } = event.detail;
    try {
      await requestPermission(kind);
    } catch (err) {
      toast({ title: $t('Could not open the permission request'), description: err.message, tone: 'danger', duration: 0 });
    }
  }

  function commitDuration() {
    const typed = String(maxDuration ?? '').trim();
    const seconds = Math.round(Number(typed));
    const cap = s.choices.max_duration_cap;
    // An emptied field is not "0": zero means no limit, and a user who
    // clears the box to type another number must not leave it unlimited.
    if (typed === '' || !Number.isFinite(seconds) || seconds < 0 || seconds > cap) {
      maxDuration = String(s.audio.max_duration);
      toast({ title: fmt($t('Enter a number of seconds from 0 to %1'), cap), tone: 'warning' });
      return;
    }
    if (seconds === s.audio.max_duration) return;
    save('audio.max_duration', seconds, () => (maxDuration = String(s.audio.max_duration)));
  }

  function jump(id, event) {
    event?.preventDefault();
    const el = document.getElementById(id);
    if (!el) return;
    const calm = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'start' });
    activeSection = id;
  }

  function watchSections() {
    if (typeof IntersectionObserver !== 'function' || !scroller) return;
    // The observer reports only the sections that changed, so the set of
    // visible ones is kept here and the first of them in page order wins.
    const visible = new Set();
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        }
        const first = SECTIONS.find((section) => visible.has(section.id));
        if (atEnd()) activeSection = SECTIONS[SECTIONS.length - 1].id;
        else if (first) activeSection = first.id;
      },
      { root: scroller, rootMargin: '-64px 0px -60% 0px', threshold: 0 },
    );
    for (const { id } of SECTIONS) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    scroller.addEventListener('scroll', onScrollEnd, { passive: true });
  }

  // The last section can never reach the activation band near the top of the
  // pane, so at the very end of the scroll it is the current one.
  function atEnd() {
    return Boolean(scroller) && scroller.scrollTop > 0 && scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2;
  }

  function onScrollEnd() {
    if (atEnd()) activeSection = SECTIONS[SECTIONS.length - 1].id;
  }

  const onFocus = () => {
    refreshPermissions().catch(() => {});
    // Plugging a headset in while the window was behind another one.
    refreshDevices();
  };

  onMount(() => {
    stopEvents = watchSettingsEvents();
    load().then(() => watchSections());
    // A grant made in System Settings is picked up on coming back; no restart.
    refreshPermissions().catch(() => {});
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
  });

  onDestroy(() => {
    stopEvents();
    observer?.disconnect();
    scroller?.removeEventListener('scroll', onScrollEnd);
    window.removeEventListener('focus', onFocus);
    document.removeEventListener('visibilitychange', onFocus);
  });

  $: deviceOptions = buildDevices($devices, $t);
  $: banners = $permissions?.banners ?? {};
  // A microphone grant makes devices appear that the first listing missed.
  let lastMic = null;
  $: if ($permissions) {
    const mic = $permissions.microphone ?? null;
    if (lastMic && lastMic !== 'authorized' && mic === 'authorized') listDevices().catch(() => {});
    lastMic = mic;
  }
  $: platform = s?.platform ?? 'linux';
  $: textScaleOptions = (s?.choices.text_scales ?? []).map((v) => ({ value: String(v), label: v === 1 ? $t('100% (default)') : `${Math.round(v * 100)}%` }));
  $: themeOptions = [
    { value: 'system', label: $t('Follow the system') },
    { value: 'light', label: $t('Light') },
    { value: 'dark', label: $t('Dark') },
  ];
  $: languageOptions = (s?.choices.languages ?? []).map((l) => ({ value: l.code, label: l.name }));
  $: scaleValue = s ? String(nearestScale(s.ui.text_scale, s.choices.text_scales)) : '1';

  function nearestScale(value, presets) {
    return presets.reduce((best, p) => (Math.abs(p - value) < Math.abs(best - value) ? p : best), presets[0] ?? 1);
  }

  function buildDevices(list, tr) {
    const options = [{ value: 'default', label: tr('System default') }];
    for (const d of list.devices) options.push({ value: String(d.index), label: `[${d.index}] ${d.name}` });
    if (list.current !== null && list.current !== undefined && !list.devices.some((d) => d.index === list.current)) {
      options.push({ value: String(list.current), label: `[${list.current}] ${tr('(not connected)')}` });
    }
    return options;
  }

  async function copyVersion() {
    const text = fmt($t('Lazy to Text %1'), s.version);
    try {
      if (window.l2t?.clipboard?.writeText) await window.l2t.clipboard.writeText(text);
      else await navigator.clipboard.writeText(text);
      toast({ title: $t('Copied to clipboard.'), tone: 'success', duration: 1500 });
    } catch (err) {
      toast({ title: $t('Could not copy'), description: err.message, tone: 'danger' });
    }
  }
</script>

<div class="flex h-full min-h-0 flex-col">
  <div bind:this={scroller} class="min-h-0 flex-1 overflow-y-auto overflow-x-hidden" data-testid="settings-scroll">
    <div class="mx-auto w-full max-w-6xl px-6 pt-6">
      <PageHeader
        title={$t('Settings')}
        description={$t('Microphone, global hotkeys, paste behaviour. Changes save automatically.')}
      />
    </div>
    <nav
      aria-label={$t('Settings sections')}
      class="sticky top-0 z-10 bg-canvas"
    >
      <!-- The rule sits inside the same gutters as the header's, not edge to edge. -->
      <div class="mx-auto w-full max-w-6xl px-6">
      <div class="flex flex-wrap gap-x-4 gap-y-1 border-b border-line py-2">
      {#each SECTIONS as section}
        <a
          href="#{section.id}"
          class="text-xs uppercase tracking-widest transition-colors duration-fast focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 {activeSection === section.id
            ? 'text-ink'
            : 'text-ink-faint hover:text-ink'}"
          aria-current={activeSection === section.id ? 'location' : undefined}
          on:click={(e) => jump(section.id, e)}
        >
          {$t(section.label)}
        </a>
      {/each}
      </div>
      </div>
    </nav>

    <div class="mx-auto w-full max-w-6xl px-6 py-4">
    {#if loadError}
      <Notice tone="danger" title={$t('Could not load the settings')}>{loadError}</Notice>
      <div class="mt-3"><Button variant="secondary" on:click={load}>{$t('Try again')}</Button></div>
    {:else if !s}
      <div class="flex flex-col gap-4" aria-busy="true">
        <Skeleton height="9rem" />
        <Skeleton height="14rem" />
        <Skeleton height="6rem" />
      </div>
    {:else}
      <div class="flex flex-col gap-4">
        <SettingsSection id="settings-audio" title={$t('Audio input')}>
          {#if banners.microphone && banners.microphone !== 'hidden'}
            <PermissionBanner kind="microphone" state={banners.microphone} on:act={onPermission} />
          {/if}

          <SettingRow label={$t('Microphone')}>
            <div class="flex items-center gap-2">
              <Select
                class="min-w-0 flex-1"
                size="sm"
                placeholder={$t('Microphone')}
                value={$devices.current === null || $devices.current === undefined ? 'default' : String($devices.current)}
                options={deviceOptions}
                on:change={onDevice}
              />
              <IconButton label={$t('Refresh the device list')} size="sm" on:click={() => listDevices({ refresh: true })}>
                <RefreshCw size={14} strokeWidth="1.7" />
              </IconButton>
            </div>
          </SettingRow>

          <SettingRow wide>
            <MicTest test={$micTest} disabled={!s.capabilities.recording_stack} on:start={onTest} />
          </SettingRow>

          {#if s.capabilities.mute_output}
            <SettingRow
              label={$t('Mute other sounds while recording')}
              hint={$t('Mutes the system output while the microphone is open, so music and notifications stay out of the recording.')}
              controlEnd
            >
              <Switch
                aria-label={$t('Mute other sounds while recording')}
                bind:checked={mute}
                on:change={(e) => save('audio.mute_output_on_record', e.detail, () => (mute = !e.detail))}
              >
                {mute ? $t('On') : $t('Off')}
              </Switch>
            </SettingRow>
          {/if}

          <SettingRow
            label={$t('Skip silence (silero VAD)')}
            hint={$t('Recognises the speech only and skips the silences. The first use downloads a small model.')}
            controlEnd
          >
            <Switch aria-label={$t('Skip silence (silero VAD)')} bind:checked={vad} on:change={(e) => save('audio.vad_enabled', e.detail, () => (vad = !e.detail))}>
              {vad ? $t('On') : $t('Off')}
            </Switch>
          </SettingRow>

          <SettingRow
            label={$t('Sound cues')}
            hint={$t('A short sound when a recording starts, stops or is cancelled.')}
            controlEnd
          >
            <Switch
              aria-label={$t('Sound cues')}
              bind:checked={feedback}
              on:change={(e) => save('audio_feedback.enabled', e.detail, () => (feedback = !e.detail))}
            >
              {feedback ? $t('On') : $t('Off')}
            </Switch>
          </SettingRow>

          <SoundSet />

          <SettingRow
            label={$t('Longest recording')}
            hint={$t('A recording stops by itself after this many seconds. 0 means no limit.')}
            forId="settings-max-duration"
          >
            <div class="flex items-center gap-2">
              <FieldControl
                id="settings-max-duration"
                type="number"
                variant="boxed"
                size="sm"
                class="w-28"
                min="0"
                max={s.choices.max_duration_cap}
                bind:value={maxDuration}
                on:change={commitDuration}
              />
              <span class="text-xs text-ink-faint">{$t('seconds')}</span>
            </div>
          </SettingRow>
        </SettingsSection>

        <SettingsSection id="settings-hotkeys" title={$t('Hotkeys')}>
          {#if banners.accessibility && banners.accessibility !== 'hidden'}
            <PermissionBanner kind="accessibility" state={banners.accessibility} on:act={onPermission} />
          {/if}
          <HotkeysCard
            hotkey={s.hotkey}
            defaults={s.defaults}
            {platform}
            storedErrors={s.hotkey_errors}
            ready={s.capabilities.recording_stack}
          />
          {#if !s.capabilities.recording_stack}
            <div class="pt-3"><Notice tone="warning">{$t('The recording stack is not running, so hotkeys cannot be changed now.')}</Notice></div>
          {/if}
        </SettingsSection>

        <SettingsSection id="settings-clipboard" title={$t('Clipboard')}>
          {#if banners.post_event && banners.post_event !== 'hidden'}
            <PermissionBanner kind="post_event" state={banners.post_event} on:act={onPermission} />
          {/if}
          <SettingRow
            label={$t('Auto-paste into the focused window')}
            hint={$t('The text is pasted as soon as it is ready. Turn it off to only copy.')}
            controlEnd
          >
            <Switch
              aria-label={$t('Auto-paste into the focused window')}
              bind:checked={autoPaste}
              on:change={(e) =>
                save('clipboard.auto_paste', e.detail, () => (autoPaste = !e.detail)).then(() => refreshPermissions().catch(() => {}))}
            >
              {autoPaste ? $t('On') : $t('Off')}
            </Switch>
          </SettingRow>
        </SettingsSection>

        <SettingsSection id="settings-appearance" title={$t('Appearance')}>
          <SettingRow label={$t('Text size')} hint={$t('Scales every text size in the app. 100% is the default.')}>
            <Select
              size="sm"
              placeholder={$t('Text size')}
              options={textScaleOptions}
              value={scaleValue}
              on:change={(e) => save('ui.text_scale', Number(e.detail.value))}
            />
          </SettingRow>
          <SettingRow label={$t('Theme')} hint={$t('Light or dark colours. Follow the system matches your desktop appearance.')}>
            <Select
              size="sm"
              placeholder={$t('Theme')}
              options={themeOptions}
              value={s.ui.theme}
              on:change={(e) => save('ui.theme', e.detail.value)}
            />
          </SettingRow>
          <SettingRow label={$t('Palette')} hint={$t('The colour scheme of the whole window, in light and in dark.')} wide>
            <PalettePicker
              value={s.ui.palette}
              choices={s.choices.palettes}
              label={$t('Palette')}
              on:change={(e) => save('ui.palette', e.detail)}
            />
          </SettingRow>
          <SettingRow label={$t('Language')} hint={$t('The language of the interface. Switches immediately.')}>
            <Select
              size="sm"
              placeholder={$t('Language')}
              options={languageOptions}
              value={s.ui.language}
              on:change={(e) => save('ui.language', e.detail.value)}
            />
          </SettingRow>
        </SettingsSection>

        <SettingsSection id="settings-startup" title={$t('Startup')}>
          <SettingRow
            label={$t('Start when I log in')}
            hint={$t('Opens Lazy to Text hidden in the tray when you sign in, so the hotkeys work right away.')}
            controlEnd
          >
            <Switch
              aria-label={$t('Start when I log in')}
              bind:checked={startAtLogin}
              on:change={(e) => save('ui.start_at_login', e.detail, () => (startAtLogin = !e.detail))}
            >
              {startAtLogin ? $t('On') : $t('Off')}
            </Switch>
          </SettingRow>
        </SettingsSection>
      </div>
    {/if}
    </div>
    <!-- At the end of the scroll area, not pinned under it: at a large text size a
         pinned footer took a fifth of a small window, and the toasts sat on it. -->
    <footer class="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-2 border-t border-line px-6 pb-20 pt-2">
      <span class="select-text text-xs text-ink-faint" aria-label={$t('Application version')}>
        {s ? fmt($t('Lazy to Text %1'), s.version) : ''}
      </span>
      <span class="flex items-center gap-1">
        <Button variant="quiet" size="sm" disabled={!s} on:click={copyVersion}>{$t('Copy version')}</Button>
        <Button variant="quiet" size="sm" on:click={() => (aboutOpen = true)}>{$t('About')}</Button>
      </span>
    </footer>
  </div>
</div>

<AboutDialog bind:open={aboutOpen} version={s?.version ?? ''} />
