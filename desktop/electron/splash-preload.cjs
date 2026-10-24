'use strict';
// The start-up page's bridge: three actions and one state feed, nothing
// else. It does not carry the connection or any of the main window's API.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('l2tSplash', {
  retry: () => ipcRenderer.send('l2t:splash:retry'),
  quit: () => ipcRenderer.send('l2t:splash:quit'),
  onState: (cb) => {
    const handler = (_event, state) => cb(state);
    ipcRenderer.on('l2t:splash:state', handler);
    return () => ipcRenderer.removeListener('l2t:splash:state', handler);
  },
});
