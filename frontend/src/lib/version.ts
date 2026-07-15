/**
 * Formats the build version string (`__APP_VERSION__`) for display in the UI.
 *
 * The raw value is produced by `git describe --tags` at image-build time (see
 * the release / nightly-images workflows) and can take several shapes:
 *   - "2026.1.23"           a clean release cut exactly on a tag
 *   - "2026.1.23+abc1234"   a clean tag build with the short commit appended
 *   - "1.0.2-6-g258ce81"    a nightly/dev build N commits past the last tag
 *
 * The last shape is the confusing one: `git describe` anchors on the newest
 * *ancestor* tag, which — right after the switch to the CalVer scheme — can
 * still be an old SemVer tag (e.g. v1.0.2). Rendering the raw string then reads
 * as a stale "1.0.2-6-g…" version.
 *
 * We therefore split the string into the bare base version and the trailing
 * short commit, dropping the `git describe` commit counter ("-6-"), so callers
 * can render e.g. "v1.0.2 · 258ce81" instead of "v1.0.2-6-g258ce81".
 */
export interface BuildVersion {
	/** Bare version core without the 'v' prefix, e.g. "1.0.2" or "2026.1.23". */
	base: string;
	/** Short commit SHA (7 chars) when the build is ahead of / off a tag, else null. */
	commit: string | null;
}

export function formatVersion(raw: string | null | undefined): BuildVersion {
	const v = (raw ?? '').trim().replace(/^v/i, '');
	if (!v) return { base: '', commit: null };

	// Base = everything before the first describe/build suffix ("-" or "+").
	const base = v.split(/[-+]/)[0];

	// Commit = the trailing hex SHA from either "+<sha>" or "-g<sha>" (git
	// describe). Truncated to 7 chars for a compact footer.
	const match = v.match(/[-+]g?([0-9a-f]{7,40})$/i);
	return { base, commit: match ? match[1].slice(0, 7) : null };
}
