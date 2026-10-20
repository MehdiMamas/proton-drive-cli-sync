/**
 * proton-sync-events — experimental, read-only probe for proton-drive-cli-sync.
 *
 * Built from the official Proton Drive CLI sources, with only three commands:
 * sign in, sign out, and report the changes in one Drive folder since the last
 * run, read from the Drive event stream. It has its own session (its own entry
 * in the system keyring) and its own data folder, so it never touches the
 * official CLI's session, cache or event bookmarks.
 *
 * This is a third-party application, not officially supported by Proton.
 */
import os from 'node:os';
import path from 'node:path';

import { run } from './cli';
import { applyDefaultCliOptions } from './cli';
import { CommandAuthLogin } from './commands/auth/commandAuthLogin';
import { CommandAuthLogout } from './commands/auth/commandAuthLogout';
import { CommandEventsChanges } from './probe/commandEventsChanges';

declare const APP_VERSION: string;
declare const SDK_VERSION: string | undefined;

// One data folder for everything (session cache, state, logs), never shared
// with the official CLI — even if PROTON_DRIVE_CACHE_DIR is set for it.
const dataDir =
    process.env.PROTON_SYNC_EVENTS_DIR || path.join(os.homedir(), '.local', 'share', 'proton-sync-events');
process.env.PROTON_DRIVE_CACHE_DIR = dataDir;
process.env.PROTON_DRIVE_LOG_LEVEL ??= 'INFO';

const COMMANDS = applyDefaultCliOptions([
    new CommandAuthLogin(),
    new CommandAuthLogout(),
    new CommandEventsChanges(),
]);

const argv = Bun.argv;
if (argv[2] === 'auth' && argv[3] === 'login') {
    console.log('This is a third-party application not officially supported by Proton.');
    console.log(`Data folder: ${dataDir}`);
}

try {
    await run(COMMANDS, {
        clientUidPrefix: 'proton-sync-events',
        appVersion: APP_VERSION,
        sdkVersion: SDK_VERSION,
        // The probe keeps its own bookmark; the CLI's events manager stays off.
        enablePersistedEvents: false,
        enableMetrics: false,
    });
    process.exit(0);
} catch (error: unknown) {
    console.error(error instanceof Error ? error.message : error);
    process.exit(1);
}
