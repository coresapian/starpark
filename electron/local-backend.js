/**
 * LinkSpot Electron - Local Backend Bootstrapper
 * Starts Docker Desktop (if needed) and launches backend dependencies.
 */

const fs = require('fs');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const LOCAL_BACKEND_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);
const DOCKER_START_TIMEOUT_MS = 120000;
const COMPOSE_UP_TIMEOUT_MS = 300000;
const BACKEND_HEALTH_TIMEOUT_MS = 180000;
const POLL_INTERVAL_MS = 2000;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function runProcess(command, args, options = {}) {
  const {
    cwd,
    env,
    timeoutMs = 120000
  } = options;

  return new Promise((resolve, reject) => {
    let stdout = '';
    let stderr = '';
    let timedOut = false;

    const child = spawn(command, args, {
      cwd,
      env,
      stdio: ['ignore', 'pipe', 'pipe']
    });

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGTERM');
    }, timeoutMs);

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });

    child.on('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });

    child.on('close', (code) => {
      clearTimeout(timer);
      if (timedOut) {
        reject(new Error(`Command timed out: ${command} ${args.join(' ')}`));
        return;
      }
      resolve({ code, stdout, stderr });
    });
  });
}

function commandWorks(command, args) {
  const result = spawnSync(command, args, {
    stdio: 'ignore',
    timeout: 6000
  });
  return !result.error && result.status === 0;
}

function resolveDockerCommand() {
  if (commandWorks('docker', ['--version'])) {
    return 'docker';
  }

  const platformCandidates = process.platform === 'darwin'
    ? [
        '/usr/local/bin/docker',
        '/opt/homebrew/bin/docker',
        '/Applications/Docker.app/Contents/Resources/bin/docker'
      ]
    : [
        '/usr/local/bin/docker',
        '/usr/bin/docker'
      ];

  for (const candidate of platformCandidates) {
    if (fs.existsSync(candidate) && commandWorks(candidate, ['--version'])) {
      return candidate;
    }
  }

  return null;
}

function resolveDockerComposeCommand() {
  if (commandWorks('docker-compose', ['version'])) {
    return 'docker-compose';
  }

  const platformCandidates = process.platform === 'darwin'
    ? ['/usr/local/bin/docker-compose', '/opt/homebrew/bin/docker-compose']
    : ['/usr/local/bin/docker-compose', '/usr/bin/docker-compose'];

  for (const candidate of platformCandidates) {
    if (fs.existsSync(candidate) && commandWorks(candidate, ['version'])) {
      return candidate;
    }
  }

  return null;
}

function isDockerDaemonReady(dockerCommand) {
  return commandWorks(dockerCommand, ['info']);
}

function getRuntimeDirectory(app) {
  if (!app.isPackaged) {
    return path.join(__dirname, '..');
  }

  const bundledRuntime = path.join(process.resourcesPath, 'runtime');
  const writableRuntime = path.join(app.getPath('userData'), 'runtime');
  const markerFile = path.join(writableRuntime, '.runtime-version');
  const bundledCompose = path.join(bundledRuntime, 'docker-compose.yml');
  const writableCompose = path.join(writableRuntime, 'docker-compose.yml');

  if (!fs.existsSync(bundledCompose)) {
    return bundledRuntime;
  }

  let requiresSync = !fs.existsSync(writableCompose);
  const currentVersion = String(app.getVersion() || '').trim();
  if (!requiresSync && currentVersion) {
    const syncedVersion = fs.existsSync(markerFile)
      ? fs.readFileSync(markerFile, 'utf-8').trim()
      : '';
    requiresSync = syncedVersion !== currentVersion;
  }

  if (requiresSync) {
    fs.mkdirSync(writableRuntime, { recursive: true });
    fs.cpSync(bundledRuntime, writableRuntime, { recursive: true, force: true });
    if (currentVersion) {
      fs.writeFileSync(markerFile, `${currentVersion}\n`, 'utf-8');
    }
  }

  return writableRuntime;
}

function isLocalBackendTarget(backendURL) {
  try {
    const parsed = new URL(String(backendURL || '').trim());
    return LOCAL_BACKEND_HOSTS.has(parsed.hostname);
  } catch {
    return false;
  }
}

async function openDockerDesktop(shell) {
  if (process.platform === 'darwin') {
    try {
      const child = spawn('open', ['-a', 'Docker'], {
        detached: true,
        stdio: 'ignore'
      });
      child.unref();
      return;
    } catch {
      // fall through
    }
    await shell.openPath('/Applications/Docker.app');
    return;
  }

  if (process.platform === 'win32') {
    try {
      const child = spawn('cmd', ['/c', 'start', '', 'Docker Desktop'], {
        detached: true,
        stdio: 'ignore'
      });
      child.unref();
    } catch {
      // ignore
    }
  }
}

async function waitForDockerDaemon(dockerCommand, timeoutMs) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (isDockerDaemonReady(dockerCommand)) {
      return true;
    }
    await delay(POLL_INTERVAL_MS);
  }
  return false;
}

function formatCommandError(result, fallbackMessage) {
  const errorText = String(result.stderr || result.stdout || '').trim();
  if (!errorText) return fallbackMessage;
  const firstLine = errorText.split('\n').find((line) => line.trim()) || fallbackMessage;
  return firstLine.trim();
}

async function isBackendHealthy(net, backendURL) {
  try {
    const response = await net.fetch(`${backendURL}/api/v1/health`, { method: 'GET' });
    return response.ok;
  } catch {
    return false;
  }
}

async function waitForBackendHealthy(net, backendURL, timeoutMs) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await isBackendHealthy(net, backendURL)) {
      return true;
    }
    await delay(POLL_INTERVAL_MS);
  }
  return false;
}

function createLocalBackendManager({ app, net, shell, log, store, onStatus }) {
  let bootstrapInFlight = null;
  let autoStartAttempted = false;

  const publishStatus = (phase, message, extra = {}) => {
    if (typeof onStatus === 'function') {
      onStatus({
        phase,
        message,
        timestamp: Date.now(),
        ...extra
      });
    }
  };

  const runComposeUp = async (dockerCommand, composeFile, env, runtimeDir) => {
    const composeArgs = ['compose', '-f', composeFile, '-p', 'linkspot', 'up', '-d', 'postgres', 'redis', 'backend'];

    if (commandWorks(dockerCommand, ['compose', 'version'])) {
      const result = await runProcess(dockerCommand, composeArgs, {
        cwd: runtimeDir,
        env,
        timeoutMs: COMPOSE_UP_TIMEOUT_MS
      });
      if (result.code === 0) {
        return;
      }
      throw new Error(formatCommandError(result, 'Failed to start backend containers.'));
    }

    const dockerComposeCommand = resolveDockerComposeCommand();
    if (!dockerComposeCommand) {
      throw new Error('Docker Compose is unavailable. Install Docker Desktop and retry.');
    }

    const fallbackArgs = ['-f', composeFile, '-p', 'linkspot', 'up', '-d', 'postgres', 'redis', 'backend'];
    const fallbackResult = await runProcess(dockerComposeCommand, fallbackArgs, {
      cwd: runtimeDir,
      env,
      timeoutMs: COMPOSE_UP_TIMEOUT_MS
    });
    if (fallbackResult.code !== 0) {
      throw new Error(formatCommandError(fallbackResult, 'Failed to start backend containers.'));
    }
  };

  const start = async ({ trigger = 'manual' } = {}) => {
    if (bootstrapInFlight) {
      return bootstrapInFlight;
    }

    bootstrapInFlight = (async () => {
      const backendURL = String(store.get('backendURL') || '').trim();
      if (!isLocalBackendTarget(backendURL)) {
        return {
          success: false,
          skipped: true,
          error: 'Local bootstrap only works with localhost backend URLs.'
        };
      }

      publishStatus('checking', 'Checking backend status…', { trigger });

      if (await isBackendHealthy(net, backendURL)) {
        publishStatus('ready', 'Backend is already online.', { trigger });
        return { success: true, alreadyRunning: true };
      }

      const dockerCommand = resolveDockerCommand();
      if (!dockerCommand) {
        publishStatus('error', 'Docker CLI not found. Install Docker Desktop first.', { trigger });
        return {
          success: false,
          error: 'Docker Desktop is not installed or Docker CLI is not on PATH.'
        };
      }

      if (!isDockerDaemonReady(dockerCommand)) {
        publishStatus('docker', 'Launching Docker Desktop…', { trigger });
        await openDockerDesktop(shell);
        const ready = await waitForDockerDaemon(dockerCommand, DOCKER_START_TIMEOUT_MS);
        if (!ready) {
          publishStatus('error', 'Docker did not become ready in time.', { trigger });
          return {
            success: false,
            error: 'Docker Desktop did not become ready. Open Docker and retry.'
          };
        }
      }

      const runtimeDir = getRuntimeDirectory(app);
      const composeFile = path.join(runtimeDir, 'docker-compose.yml');
      if (!fs.existsSync(composeFile)) {
        publishStatus('error', 'Bundled Docker runtime files are missing.', { trigger });
        return {
          success: false,
          error: 'Local runtime files are missing from the app bundle.'
        };
      }

      publishStatus('compose', 'Starting local backend containers…', { trigger });
      const composeEnv = {
        ...process.env,
        BUILD_TARGET: 'development',
        ENVIRONMENT: 'development',
        CORS_ORIGINS: '["http://localhost","http://localhost:3000","http://localhost:5173","app://linkspot"]',
        DEBUG: 'true',
        LOG_LEVEL: process.env.LOG_LEVEL || 'INFO'
      };

      try {
        await runComposeUp(dockerCommand, composeFile, composeEnv, runtimeDir);
      } catch (error) {
        log.warn('Local backend compose startup failed:', error.message);
        publishStatus('error', error.message, { trigger });
        return { success: false, error: error.message };
      }

      publishStatus('health', 'Waiting for backend health check…', { trigger });
      const healthy = await waitForBackendHealthy(net, backendURL, BACKEND_HEALTH_TIMEOUT_MS);
      if (!healthy) {
        publishStatus('error', 'Backend started but health checks did not pass.', { trigger });
        return {
          success: false,
          error: 'Backend did not become healthy. Check Docker logs for details.'
        };
      }

      publishStatus('ready', 'Local backend is online.', { trigger });
      return { success: true };
    })().catch((error) => {
      const message = error && error.message ? error.message : 'Failed to start local backend.';
      publishStatus('error', message, { trigger });
      return { success: false, error: message };
    }).finally(() => {
      bootstrapInFlight = null;
    });

    return bootstrapInFlight;
  };

  const autoStartIfEnabled = async () => {
    if (autoStartAttempted) {
      return { success: true, skipped: true };
    }
    autoStartAttempted = true;

    if (store.get('autoStartLocalBackend') === false) {
      return { success: true, skipped: true };
    }

    if (!isLocalBackendTarget(store.get('backendURL'))) {
      return { success: true, skipped: true };
    }

    return start({ trigger: 'auto' });
  };

  return {
    start,
    autoStartIfEnabled,
    isLocalBackendTarget: () => isLocalBackendTarget(store.get('backendURL'))
  };
}

module.exports = { createLocalBackendManager };
