'use strict';
// The renderer's window onto the main process. Nothing here exposes Node:
// each entry is one named capability, so a compromised page can ask for a
// file dialog but cannot read a file. The main process also checks who is
// asking before it answers any of them.

const { contextBridge, ipcRenderer, webUtils } = require('electron');

// Electron wraps a handler's error as "Error invoking remote method 'x': Error: msg".
// The page gets the message alone.
const invoke = (channel, ...args) => ipcRenderer.invoke(channel, ...args).catch((err) => {
  const message = String((err && err.message) || err).replace(/^Error invoking remote method '[^']*': (?:Error: )?/, '');
  throw new Error(message);
});

const on = (channel, cb) => {
  const handler = (_event, payload) => cb(payload);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
};

contextBridge.exposeInMainWorld('l2t', {
  platform: process.platform,
  // The CURRENT connection {port, token}; after a restart it is the new one.
  // Rejects while the engine is not running.
  connection: () => invoke('l2t:connection'),
  // A dropped File no longer carries its path; the page asks for it here.
  pathForFile: (file) => webUtils.getPathForFile(file),
  setTheme: (choice) => ipcRenderer.send('l2t:theme', choice),
  dialog: {
    openFile: (options) => invoke('l2t:dialog:open-file', options),
    openDirectory: (options) => invoke('l2t:dialog:open-directory', options),
    saveFile: (options) => invoke('l2t:dialog:save-file', options),
    confirm: (options) => invoke('l2t:dialog:confirm', options),
  },
  shell: {
    openExternal: (url) => invoke('l2t:shell:open-external', url),
    showItemInFolder: (path) => invoke('l2t:shell:show-item', path),
  },
  window: {
    show: () => ipcRenderer.send('l2t:window:show'),
    quit: () => ipcRenderer.send('l2t:quit'),
    relaunch: () => ipcRenderer.send('l2t:relaunch'),
  },
  clipboard: {
    writeText: (text) => invoke('l2t:clipboard:write', text),
  },
  // The runtime (the Python engine behind the window).
  backend: {
    // cb({ code, signal }) when the engine process has ended, or stopped answering.
    onExit: (cb) => on('l2t:backend-exit', cb),
    // Starts it again. Resolves with the new { port, token } once it is
    // ready; rejects with an Error whose message is fit to show.
    restart: async () => {
      const answer = await invoke('l2t:backend:restart');
      if (answer && answer.ok) return answer.connection;
      throw new Error((answer && answer.message) || 'The engine could not be restarted.');
    },
    // cb({ port, token }) after any restart, in every window.
    onRestarted: (cb) => on('l2t:backend-restarted', cb),
    // Where the runtime writes its log: a path, or null when unknown.
    logPath: () => {
      const value = ipcRenderer.sendSync('l2t:backend:log-path');
      return typeof value === 'string' && value ? value : null;
    },
  },
  onNavigate: (cb) => on('l2t:navigate', cb),
  onFileOpen: (cb) => on('l2t:file-open', cb),
  // Kept for the renderer that still calls it; the same event as backend.onExit.
  onBackendExit: (cb) => on('l2t:backend-exit', cb),
});
