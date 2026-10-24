'use strict';
// The few strings the main process owns: the tray, the application menu,
// the start-up and "already running" windows. Everything else is drawn by
// the renderer, which has its own catalogue. The language is the runtime's
// `ui.language`; until the runtime has answered it is the system's.

const STRINGS = {
  en: {
    appName: 'Lazy to Text',
    show: 'Show window',
    quit: 'Quit',
    quitApp: 'Quit Lazy to Text',
    about: 'About Lazy to Text',
    aboutDescription: 'Local speech recognition with Whisper, Parakeet and GigaAM on ONNX Runtime. It runs on the processor; Apple Silicon uses CoreML.',
    aboutLicence: 'Released under the MIT licence.',
    hideApp: 'Hide Lazy to Text',
    hideOthers: 'Hide Others',
    showAll: 'Show All',
    restartEngine: 'Restart engine',
    settings: 'Settings…',
    edit: 'Edit',
    view: 'View',
    window: 'Window',
    minimize: 'Minimize',
    zoom: 'Zoom',
    close: 'Close',
    bringAllToFront: 'Bring all to front',
    screens: {
      transcribe: 'Transcribe',
      models: 'Models',
      history: 'History',
      postprocessing: 'Post-processing',
      settings: 'Settings',
      logs: 'Logs',
    },
    tip: {
      idle: 'Lazy to Text: idle',
      recording: 'Lazy to Text: recording',
      processing: 'Lazy to Text: transcribing',
      model_loading: 'Lazy to Text: loading model',
      stopped: 'Lazy to Text: engine stopped',
    },
    alreadyRunning: 'Another copy of Lazy to Text is already running. Use its tray icon to bring it back, or quit it first.',
    splash: {
      loadingTitle: 'Starting Lazy to Text',
      loadingBody: 'Starting the speech engine. The first start can take a minute.',
      errorTitle: 'The engine did not start',
      log: 'Log file',
      retry: 'Retry',
      quit: 'Quit',
      details: 'Details',
    },
    startFailures: {
      missing: 'The engine is missing: {path}',
      exited: 'The engine stopped while starting (exit code {code}).',
      timeout: 'The engine did not start within {seconds} seconds.',
      generic: 'The engine could not be started.',
    },
    restartFailed: 'The engine could not be restarted.',
  },
  ru: {
    appName: 'Lazy to Text',
    show: 'Показать окно',
    quit: 'Выйти',
    quitApp: 'Выйти из Lazy to Text',
    about: 'О приложении Lazy to Text',
    aboutDescription: 'Локальное распознавание речи на Whisper, Parakeet и GigaAM поверх ONNX Runtime. Работает на процессоре; на Apple Silicon используется CoreML.',
    aboutLicence: 'Распространяется по лицензии MIT.',
    hideApp: 'Скрыть Lazy to Text',
    hideOthers: 'Скрыть остальные',
    showAll: 'Показать все',
    restartEngine: 'Перезапустить движок',
    settings: 'Настройки…',
    edit: 'Правка',
    view: 'Вид',
    window: 'Окно',
    minimize: 'Свернуть',
    zoom: 'Увеличить',
    close: 'Закрыть',
    bringAllToFront: 'Все окна на передний план',
    screens: {
      transcribe: 'Расшифровка',
      models: 'Модели',
      history: 'История',
      postprocessing: 'Постобработка',
      settings: 'Настройки',
      logs: 'Журнал',
    },
    tip: {
      idle: 'Lazy to Text: ожидание',
      recording: 'Lazy to Text: запись',
      processing: 'Lazy to Text: расшифровка',
      model_loading: 'Lazy to Text: загрузка модели',
      stopped: 'Lazy to Text: движок остановлен',
    },
    alreadyRunning: 'Другая копия Lazy to Text уже запущена. Верните её значком в трее или сначала закройте её.',
    splash: {
      loadingTitle: 'Запуск Lazy to Text',
      loadingBody: 'Запускается движок распознавания. Первый запуск может занять минуту.',
      errorTitle: 'Движок не запустился',
      log: 'Файл журнала',
      retry: 'Повторить',
      quit: 'Выйти',
      details: 'Подробности',
    },
    startFailures: {
      missing: 'Движок не найден: {path}',
      exited: 'Движок остановился при запуске (код выхода {code}).',
      timeout: 'Движок не запустился за {seconds} с.',
      generic: 'Не удалось запустить движок.',
    },
    restartFailed: 'Не удалось перезапустить движок.',
  },
};

/** 'ru' for a Russian value or locale, 'en' for everything else. */
function normalise(value) {
  return /^ru\b/i.test(String(value || '').replace('_', '-')) ? 'ru' : 'en';
}

function forLanguage(value) {
  return STRINGS[normalise(value)];
}

function format(template, values = {}) {
  return String(template).replace(/\{(\w+)\}/g, (_m, key) => (key in values ? String(values[key]) : ''));
}

module.exports = { STRINGS, normalise, forLanguage, format };
