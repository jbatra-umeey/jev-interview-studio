# Mobile dependency security

Reviewed October 10, 2026. The audit is not clean: **14 high-severity package findings remain**, propagated from the two upstream advisories below. The original SDK 54 install reported 35 findings (23 high, 12 moderate).

## Applied fixes

- Upgraded Expo to 57.0.27, React Native to 0.86.3, React to 19.2.3, and native modules to the versions selected by Expo's SDK compatibility check.
- Added the required `expo-asset` peer dependency for `expo-audio`.
- Refreshed transitive dependencies, including PostCSS 8.5.29, and removed the vulnerable legacy Jest/js-yaml dependency chains through the SDK upgrade.
- Overrode only `xcode`'s `uuid` dependency to 11.1.1. This version includes the buffer-bounds fix and retains CommonJS `uuid.v4()`, the API used by xcode 3.0.1. Do not replace this with an ESM-only major without revalidating native project generation.
- Committed `package-lock.json`; CI installs with `npm ci`, checks SDK alignment, and exports Android and iOS bundles.

## Unresolved upstream advisories

| Package | Advisory | Exposure |
| --- | --- | --- |
| braces 3.0.3 | [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | Nested brace patterns can exhaust the stack. Installed through Metro's file matching tooling. |
| node-forge 1.4.0 | [GHSA-86w9-cpqp-85rv](https://github.com/advisories/GHSA-86w9-cpqp-85rv) | RSA signature verification accepts malformed nested DigestAlgorithm elements. Installed through Expo CLI and its code-signing certificate tooling. |

Neither advisory lists a published patched version as of the review date. They are development/build-tool dependencies in this project; they are not directly imported by `App.js`. This does not establish that every tooling path is unexploitable. Use trusted source trees and build configuration, and avoid feeding untrusted glob patterns or certificates to these tools until upstream fixes are available.

The 14 npm findings include dependent packages affected by these same two root advisories; they are not 14 independent vulnerabilities. No advisory is suppressed, no audit threshold is lowered, and no package is renamed to hide findings. `npm audit` continues to return a failing exit code. The functional CI checks do not constitute security clearance.

## Recheck

```sh
cd mobile
npm ci
npm run check
npx expo-doctor@latest
npm run export:mobile
npm audit
```

When upstream patches are released, update within the supported Expo dependency set, refresh the lockfile, rerun these checks, and revise this document. Do not use `npm audit fix --force` blindly: its proposed Expo downgrade does not reliably resolve these unpatched transitive advisories and can break SDK compatibility.

Native device recording, secure storage, and signed native release builds require separate device/release testing after this SDK upgrade.
