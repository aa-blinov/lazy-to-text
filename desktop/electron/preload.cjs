'use strict';
// The renderer's window onto the main process. Nothing here exposes Node:
// each entry is one named capability, so a compromised page can ask for a
// file dialog but cannot read a file.

const { contextBridge, ipcRenderer } = require('electron');

const on = (channel, cb) => {
  const handler = (_event, payload) => cb(payload);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
};

contextBridge.exposeInMainWorld('l2t', {
  platform: process.platform,
  connection: () => ipcRenderer.invoke('l2t:connection'),
  setTheme: (choice) => ipcRenderer.send('l2t:theme', choice),
  dialog: {
    openFile: (options) => ipcRenderer.invoke('l2t:dialog:open-file', options),
    openDirectory: (options) => ipcRenderer.invoke('l2t:dialog:open-directory', options),
    saveFile: (options) => ipcRenderer.invoke('l2t:dialog:save-file', options),
    confirm: (options) => ipcRenderer.invoke('l2t:dialog:confirm', options),
  },
  shell: {
    openExternal: (url) => ipcRenderer.invoke('l2t:shell:open-external', url),
    showItemInFolder: (path) => ipcRenderer.invoke('l2t:shell:show-item', path),
  },
  window: {
    show: () => ipcRenderer.send('l2t:window:show'),
    quit: () => ipcRenderer.send('l2t:quit'),
    relaunch: () => ipcRenderer.send('l2t:relaunch'),
  },
  clipboard: {
    writeText: (text) => ipcRenderer.invoke('l2t:clipboard:write', text),
  },
  onNavigate: (cb) => on('l2t:navigate', cb),
  onFileOpen: (cb) => on('l2t:file-open', cb),
  onBackendExit: (cb) => on('l2t:backend-exit', cb),
  // Capsule and popup windows.
  overlay: {
    onShow: (cb) => on('l2t:overlay:show', cb),
  },
  popup: {
    onShow: (cb) => on('l2t:popup:show', cb),
    close: () => ipcRenderer.send('l2t:popup:close'),
    copy: (text) => ipcRenderer.invoke('l2t:clipboard:write', text),
  },
});
