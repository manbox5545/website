# MPoxel integrated apps

This package combines the old `index.html` land finder and `documents.html` people lookup into one responsive **Connected Records** page.

## Files
- `index.html` — combined Land Finder + People Directory. `index.html?tab=people` opens the People Directory.
- `documents.html` — compatibility redirect to the combined People Directory.
- `id.html` — IDLink registration and profile editor.
- `pay.html` — P-Pay demo wallet, linked to the same Firebase Authentication project.
- `HRS-0015545.pdf` — the supplied sample land document.

## Shared profile flow
1. IDLink creates/signs in the user through Firebase Authentication.
2. IDLink stores the private profile at `profiles/{uid}` and publishes a limited profile card to `publicProfiles/{uid}`.
3. IDLink lookups, the People Directory, and P-Pay recipient search use `publicProfiles`, so new profiles and profile edits can appear through Firebase realtime listeners.
4. P-Pay still uses the authenticated user's private `profiles/{uid}` record to verify that the signed-in account owns the ID.

The shared ID is the Firebase UID plus a stable `uniqueId` (for example `ID-ABCD-2345`). Do not match users by display name alone where a unique ID is available.

## Deploy
Upload these files to the same HTTPS site/folder, keeping the filenames. Firebase modules require a web server/HTTPS (localhost is fine for local testing); opening files with `file://` may not work.

The HTML files use the Firebase project configuration already present in the uploaded IDLink/P-Pay files. Verify that this is the intended project before deployment.

## Firebase Realtime Database rules
The app code cannot set database rules for you. Review the existing rules in Firebase Console before changing them. The intended identity rules are:
- `profiles/{uid}`: read/write only by the authenticated owner.
- `publicProfiles`: readable only by authenticated users; each user can write only `publicProfiles/{their uid}`.
- `landRecords`: public read only if land records are intentionally public; writes should be restricted to an administrator.

A conceptual rules fragment for those paths is:

```json
{
  "rules": {
    "profiles": {
      "$uid": {
        ".read": "auth != null && auth.uid === $uid",
        ".write": "auth != null && auth.uid === $uid"
      }
    },
    "publicProfiles": {
      ".read": "auth != null",
      "$uid": {
        ".write": "auth != null && auth.uid === $uid"
      }
    },
    "landRecords": {
      ".read": true,
      ".write": false
    }
  }
}
```

This is only a fragment/example, not a drop-in replacement for your existing rules. Merge it carefully with your current wallet/transaction rules. The `publicProfiles` read is intentionally limited to safe display fields; email is copied only when the user explicitly enables sharing.

## Important limitations
- Existing users are copied into `publicProfiles` the next time they sign in to IDLink. Newly registered users are published automatically.
- Profile syncing depends on Firebase permissions allowing the user's own write to `publicProfiles/{uid}` and authenticated reads of `publicProfiles`.
- The HRS record remains a local demonstration fallback. Remote records may be read from `landRecords` if your database contains them. A land record is not proof of ownership by itself; link it to a verified user/UID on the server if that relationship matters.
- P-Pay remains a **simulated-credit prototype**. Its current browser-side multi-user balance updates are not secure or atomic enough for real money. Do not use it for real payments or loosen database rules to permit arbitrary users to edit each other's balances. Use a trusted backend/Cloud Functions with server-side validation and atomic transactions before handling value.
- Do not store passwords in profile records or expose them in `publicProfiles`.
