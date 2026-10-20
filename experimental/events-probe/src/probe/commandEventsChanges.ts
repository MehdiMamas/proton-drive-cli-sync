import fs from 'node:fs';
import path from 'node:path';

import { type NodeEntity, NodeType, type ProtonDriveClient, ValidationError } from '@protontech/drive-sdk';

import { type ActionArgs, type Command, formatSize, getName, type Options, sanitizeTerminalText } from '../cli';
import {
    type Change,
    detectChanges,
    initialize,
    type ProbeEvent,
    type ProbeNode,
    type ProbeSdk,
    type ProbeState,
    type RunResult,
    STATE_VERSION,
} from './changesLogic';

const STATE_FILE = 'changes-state.json';
const LOCK_FILE = 'changes.lock';

export class CommandEventsChanges implements Command {
    group = 'events';
    name = 'changes';
    help =
        'Reports what changed inside one Drive folder since the previous run, using the Drive event stream. ' +
        'The first run (or a run on another folder) only sets the starting point. Read-only: nothing is written to Drive.';
    args = ['path'];
    options: Options = {
        keep: {
            type: 'boolean',
            short: 'k',
            default: false,
            help: 'Do not advance the bookmark: the next run reports the same changes again.',
        },
        events: {
            type: 'boolean',
            short: 'e',
            default: false,
            help: 'Also list every event read, including those that do not concern the folder.',
        },
    };

    async action({ sdk, paths, config, args: [pathString], options: { json, keep, events } }: ActionArgs) {
        const lockPath = path.join(config.appDir, LOCK_FILE);
        if (!acquireLock(lockPath)) {
            throw new ValidationError(`Another run is in progress (lock: ${lockPath})`);
        }
        try {
            const statePath = path.join(config.appDir, STATE_FILE);
            const state = loadState(statePath);

            // Known folder: read it by its id (one node, usually from the cache)
            // instead of listing "My files" to find it by name on every run.
            let folder: NodeEntity | undefined;
            if (state && state.folderPath === pathString) {
                folder = await getKnownFolder(sdk, state.folderUid);
            }
            folder ??= await paths.getNode(pathString);
            if (folder.type !== NodeType.Folder) {
                throw new ValidationError(`${pathString} is not a folder`);
            }
            if (folder.trashTime) {
                throw new ValidationError(`${pathString} is in the trash`);
            }

            const probeSdk = adaptSdk(sdk);

            let result: RunResult;
            if (!state || state.folderUid !== folder.uid) {
                result = await initialize(probeSdk, {
                    uid: folder.uid,
                    path: pathString,
                    scopeId: folder.treeEventScopeId,
                });
                if (state) {
                    result.notes.unshift(`The watched folder changed (was ${state.folderPath}).`);
                }
            } else {
                result = await detectChanges(probeSdk, { ...state, folderPath: pathString });
            }

            let saved = false;
            if (result.newState === null) {
                removeFile(statePath);
                saved = true;
            } else if (!keep || result.initialized) {
                saveState(statePath, result.newState);
                saved = true;
            }
            print(pathString, result, saved, json, events);
        } finally {
            releaseLock(lockPath);
        }
    }
}

/** The watched folder by its id; undefined when it is gone or trashed, so the
 * caller falls back to finding it by name. Network errors propagate. */
async function getKnownFolder(sdk: ProtonDriveClient, uid: string): Promise<NodeEntity | undefined> {
    try {
        const node = await sdk.getNode(uid);
        return node.trashTime || node.type !== NodeType.Folder ? undefined : node;
    } catch (error: unknown) {
        if (error instanceof ValidationError) {
            return undefined;
        }
        throw error;
    }
}

function adaptSdk(sdk: ProtonDriveClient): ProbeSdk {
    return {
        async getHierarchy(nodeUid: string): Promise<ProbeNode[] | null> {
            try {
                const chain = await sdk.getNodeHierarchy(nodeUid);
                return chain.map(toProbeNode);
            } catch (error: unknown) {
                // "Item not found" and friends: the node is gone. Anything else
                // (network, server) must fail the run so the bookmark stays put.
                if (error instanceof ValidationError) {
                    return null;
                }
                throw error;
            }
        },
        async listChildren(folderUid: string): Promise<ProbeNode[]> {
            const out: ProbeNode[] = [];
            for await (const child of sdk.iterateFolderChildren(folderUid)) {
                out.push(toProbeNode(child));
            }
            return out;
        },
        async *iterateEvents(scopeId: string, lastEventId?: string): AsyncIterable<ProbeEvent> {
            for await (const event of sdk.iterateEvents(scopeId, lastEventId)) {
                const e = event as {
                    type: string;
                    eventId: string;
                    nodeUid?: string;
                    parentNodeUid?: string;
                    isTrashed?: boolean;
                };
                yield {
                    type: e.type,
                    eventId: e.eventId,
                    nodeUid: e.nodeUid,
                    parentNodeUid: e.parentNodeUid,
                    isTrashed: e.isTrashed,
                };
            }
        },
    };
}

function toProbeNode(node: NodeEntity): ProbeNode {
    const revision = node.activeRevision;
    return {
        uid: node.uid,
        parentUid: node.parentUid,
        name: getName(node),
        type: node.type,
        trashed: !!node.trashTime,
        size: revision?.claimedSize ?? node.totalStorageSize,
        modificationTime: (revision?.claimedModificationTime ?? node.modificationTime)?.toISOString(),
        revisionUid: revision?.uid,
        sha1: revision?.claimedDigests?.sha1,
    };
}

function loadState(statePath: string): ProbeState | null {
    try {
        const state = JSON.parse(fs.readFileSync(statePath, 'utf8')) as ProbeState;
        return state.version === STATE_VERSION && state.lastEventId ? state : null;
    } catch {
        return null;
    }
}

function saveState(statePath: string, state: ProbeState): void {
    fs.mkdirSync(path.dirname(statePath), { recursive: true, mode: 0o700 });
    const tmp = `${statePath}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2), { mode: 0o600 });
    fs.renameSync(tmp, statePath);
}

function removeFile(filePath: string): void {
    try {
        fs.unlinkSync(filePath);
    } catch {}
}

function acquireLock(lockPath: string): boolean {
    fs.mkdirSync(path.dirname(lockPath), { recursive: true, mode: 0o700 });
    try {
        fs.writeFileSync(lockPath, String(process.pid), { flag: 'wx', mode: 0o600 });
        return true;
    } catch {
        // A lock left by a process that no longer exists is taken over.
        try {
            const pid = Number(fs.readFileSync(lockPath, 'utf8'));
            if (pid > 0) {
                process.kill(pid, 0);
                return false;
            }
        } catch {}
        fs.writeFileSync(lockPath, String(process.pid), { mode: 0o600 });
        return true;
    }
}

function releaseLock(lockPath: string): void {
    removeFile(lockPath);
}

const SYMBOL: Record<Change['action'], string> = {
    created: '+',
    modified: '~',
    revised: '=',
    moved: '>',
    removed: '-',
};

function print(folderPath: string, result: RunResult, saved: boolean, json: boolean, showEvents: boolean): void {
    if (json) {
        const out: Record<string, unknown> = {
            folder: folderPath,
            initialized: result.initialized,
            eventsRead: result.eventsRead,
            changes: result.changes,
            notes: result.notes,
            bookmarkAdvanced: saved,
        };
        if (showEvents) {
            out.events = result.events;
        }
        console.log(sanitizeTerminalText(JSON.stringify(out)));
        return;
    }
    console.log(`Watched folder: ${sanitizeTerminalText(folderPath)}`);
    for (const note of result.notes) {
        console.log(sanitizeTerminalText(note));
    }
    if (result.initialized) {
        console.log('Next run reports the changes made from now on.');
        return;
    }
    console.log(`Events read on the volume: ${result.eventsRead}`);
    if (showEvents) {
        for (const e of result.events) {
            const node = e.nodeUid ? ` ${shortUid(e.nodeUid)}` : '';
            console.log(sanitizeTerminalText(`  event ${e.type}${node}: ${e.outcome}`));
        }
    }
    console.log(`Changes in the folder: ${result.changes.length}`);
    for (const c of result.changes) {
        const kind = c.type === 'folder' ? 'folder' : 'file';
        const where = c.from ? `${c.from} -> ${c.path}` : c.path;
        const details: string[] = [];
        if (c.action !== 'removed' && kind === 'file' && c.size !== undefined) {
            details.push(formatSize(c.size, true));
        }
        if (c.action !== 'removed' && c.modificationTime) {
            details.push(`modified ${c.modificationTime.replace('T', ' ').slice(0, 19)} UTC`);
        }
        if (c.reason) {
            details.push(c.reason);
        }
        const suffix = details.length > 0 ? `  (${details.join(', ')})` : '';
        console.log(sanitizeTerminalText(`  ${SYMBOL[c.action]} ${c.action.padEnd(8)} ${kind.padEnd(6)} ${where}${suffix}`));
    }
    if (!saved) {
        console.log('Bookmark NOT advanced (--keep): the next run reports these changes again.');
    }
}

/** Last part of a node uid, enough to tell events apart. */
function shortUid(uid: string): string {
    const linkId = uid.split('~').pop() ?? uid;
    return linkId.length > 10 ? `…${linkId.slice(-10)}` : linkId;
}
