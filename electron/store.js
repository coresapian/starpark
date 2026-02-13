/**
 * LinkSpot Electron - Settings Store
 * Persistent settings via electron-store
 */

const Store = require('electron-store');

const schema = {
  backendURL: {
    type: 'string',
    default: 'http://localhost:8000'
  },
  notifications: {
    type: 'boolean',
    default: true
  },
  windowBounds: {
    type: 'object',
    properties: {
      x: { type: 'number' },
      y: { type: 'number' },
      width: { type: 'number' },
      height: { type: 'number' }
    },
    default: {}
  }
};

const store = new Store({ schema });

module.exports = store;
