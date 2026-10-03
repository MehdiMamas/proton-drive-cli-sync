# When a file is uploaded again

Proton Drive Sync uploads a file from your machine to Drive. It does not download remote edits. A file is sent again only when this pass cannot show that Drive already has the same bytes.

The check is per file, in this order. The first row that matches decides.

| Situation | Sent again? |
| --- | --- |
| Drive has no file with this name | Yes |
| The local file cannot be read | Yes. The upload then reports the real error |
| The listing has no file size | Yes |
| The local size and the remote size differ | Yes |
| You passed `--verify-hash` and the listing has a SHA-1 | Yes only when the hashes differ |
| This folder was fully synced before, and this file's size and modification time are still the ones from that pass | No |
| The listing has a SHA-1 | Yes only when it differs from the local file |
| The listing's claimed modification time is within 2 seconds of the local modification time | No |
| None of the above (same size, nothing else to compare) | Yes |

`--verify-hash` is the explicit content check: for equal sizes it compares SHA-1 before trusting the previous pass.

A folder whose signature has not changed is not listed at all. The files inside are not hashed and not uploaded. That signature is the directory's modification time plus each direct file's name, size and modification time. It is written only after that folder's uploads and deletions all succeeded. The signature's shape is unchanged from previous versions, so an existing cache file still loads and unchanged folders are still skipped.

`--ignore-cache` lists the folder again and does not trust the previous pass's per-file record. It does not by itself force every file to upload: an equal-size file whose remote SHA-1 matches is still left in place.

## What this does not catch

An edit that keeps both the size and the modification time still matches the previous successful pass. `cp -p` and `rsync -t` can do that: the bytes differ, the size is the same, and the old modification time is put back. A normal pass skips that file.

`--ignore-cache` and `--verify-hash` send it when the listing includes a SHA-1. `--ignore-cache` drops the previous record and then compares that digest. `--verify-hash` compares the digest before trusting the previous record.

If the listing has no SHA-1 and the claimed modification time is still within 2 seconds of the local one, the file is not sent. Nothing is left that can show the bytes changed, and the times agree. That includes a pass with `--ignore-cache`.

## What is read from disk

Unchanged files are not hashed. Hashing runs only for an equal-size file that this pass actually has to check: `--verify-hash` asked for it, or the previous pass's record is missing or different and the listing includes a SHA-1. A folder skipped by the cache never reaches this check.
