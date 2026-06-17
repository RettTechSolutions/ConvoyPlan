<!--
	ChangelogModal — shows the GitHub release notes once after a version upgrade.

	"Version, not commit": we compare only the x.y.z core of the build version
	(stripping "+sha" build metadata and "-3-gabc" describe suffixes), so a new
	commit on the same release never re-triggers the dialog — only a real version
	bump does. The last-seen version is persisted in localStorage; on the very
	first run we record it silently so existing users aren't greeted out of the
	blue.
-->
<script lang="ts">
	import { onMount } from 'svelte';

	interface Changelog {
		version: string | null;
		name: string | null;
		body: string | null;
		html_url: string | null;
		published_at: string | null;
	}

	const STORAGE_KEY = 'cp-changelog-seen-version';

	let open = $state(false);
	let changelog = $state<Changelog | null>(null);

	/** Bare "x.y.z" core of a version string (drops v-prefix, +meta, -suffix). */
	function versionCore(v: string | null | undefined): string | null {
		if (!v) return null;
		const core = v.replace(/^[vV]/, '').split('+')[0].split('-')[0].trim();
		return /^\d/.test(core) ? core : null;
	}

	function close() {
		open = false;
		const core = versionCore(__APP_VERSION__);
		if (core) {
			try { localStorage.setItem(STORAGE_KEY, core); } catch { /* ignore */ }
		}
	}

	onMount(async () => {
		// Skip on the public tracking / share / setup surfaces — the dialog is for
		// the operating users of the main app, not embedded/public views.
		const path = window.location.pathname;
		if (path.startsWith('/track') || path.startsWith('/share') || path.startsWith('/setup')) return;

		const current = versionCore(__APP_VERSION__);
		if (!current) return;

		let seen: string | null = null;
		try { seen = localStorage.getItem(STORAGE_KEY); } catch { /* ignore */ }

		// First run on this device → remember silently, don't interrupt.
		if (!seen) {
			try { localStorage.setItem(STORAGE_KEY, current); } catch { /* ignore */ }
			return;
		}
		// Same version (possibly a new commit) → nothing to announce.
		if (seen === current) return;

		// A genuine version change: fetch the notes and show them once.
		try {
			const resp = await fetch('/api/version/changelog');
			if (!resp.ok) return;
			const data = (await resp.json()) as Changelog;
			if (data.body && data.body.trim()) {
				changelog = data;
				open = true;
			} else {
				// No notes available — don't nag, just mark as seen.
				try { localStorage.setItem(STORAGE_KEY, current); } catch { /* ignore */ }
			}
		} catch {
			// Offline / unreachable — keep the unseen state so we retry next load.
		}
	});

	// --- Minimal, XSS-safe markdown rendering for the release body -----------
	function escapeHtml(s: string): string {
		return s
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;');
	}

	function renderInline(s: string): string {
		let out = escapeHtml(s);
		// `code`
		out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
		// **bold**
		out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
		// [text](http…) — only http(s) links to stay safe
		out = out.replace(
			/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
			'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
		);
		return out;
	}

	function renderMarkdown(md: string): string {
		const lines = md.replace(/\r\n/g, '\n').split('\n');
		const html: string[] = [];
		let listType: 'ul' | 'ol' | null = null;

		const closeList = () => {
			if (listType) { html.push(`</${listType}>`); listType = null; }
		};

		for (const raw of lines) {
			const line = raw.trimEnd();
			if (!line.trim()) { closeList(); continue; }

			const heading = line.match(/^(#{1,4})\s+(.*)$/);
			if (heading) {
				closeList();
				const level = Math.min(heading[1].length + 1, 5); // h2..h5
				html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
				continue;
			}

			const bullet = line.match(/^\s*[-*]\s+(.*)$/);
			if (bullet) {
				if (listType !== 'ul') { closeList(); html.push('<ul>'); listType = 'ul'; }
				html.push(`<li>${renderInline(bullet[1])}</li>`);
				continue;
			}

			const numbered = line.match(/^\s*\d+\.\s+(.*)$/);
			if (numbered) {
				if (listType !== 'ol') { closeList(); html.push('<ol>'); listType = 'ol'; }
				html.push(`<li>${renderInline(numbered[1])}</li>`);
				continue;
			}

			closeList();
			html.push(`<p>${renderInline(line)}</p>`);
		}
		closeList();
		return html.join('\n');
	}

	let bodyHtml = $derived(changelog?.body ? renderMarkdown(changelog.body) : '');
</script>

{#if open && changelog}
	<div class="cl-backdrop" onclick={close} role="presentation">
		<div
			class="cl-modal"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => { if (e.key === 'Escape') close(); }}
			role="dialog"
			aria-modal="true"
			aria-labelledby="cl-title"
			tabindex="-1"
		>
			<div class="cl-header">
				<div>
					<span class="cl-badge">Neue Version</span>
					<h2 id="cl-title">{changelog.name ?? `Version ${changelog.version}`}</h2>
				</div>
				<button class="cl-close" onclick={close} aria-label="Schließen">✕</button>
			</div>
			<div class="cl-body">
				{@html bodyHtml}
			</div>
			<div class="cl-footer">
				{#if changelog.html_url}
					<a href={changelog.html_url} target="_blank" rel="noopener noreferrer" class="cl-link">
						Auf GitHub ansehen ↗
					</a>
				{/if}
				<button class="cl-ok" onclick={close}>Verstanden</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.cl-backdrop {
		position: fixed; inset: 0; z-index: 2000;
		background: rgba(0,0,0,.55);
		display: flex; align-items: center; justify-content: center;
		padding: 1rem;
	}
	.cl-modal {
		background: var(--surface-1, #fff);
		color: var(--text-1, #1a1a1a);
		width: min(560px, 100%);
		max-height: 85vh;
		border-radius: 14px;
		box-shadow: 0 12px 48px rgba(0,0,0,.5);
		display: flex; flex-direction: column;
		overflow: hidden;
	}
	.cl-header {
		display: flex; justify-content: space-between; align-items: flex-start;
		gap: 1rem; padding: 1.1rem 1.25rem .75rem;
		border-bottom: 1px solid var(--border, rgba(0,0,0,.1));
	}
	.cl-badge {
		display: inline-block; font-size: .68rem; font-weight: 700;
		text-transform: uppercase; letter-spacing: .05em;
		color: #fff; background: var(--color-primary, #E23D28);
		padding: .15rem .5rem; border-radius: 10px; margin-bottom: .35rem;
	}
	.cl-header h2 { margin: 0; font-size: 1.15rem; }
	.cl-close {
		background: none; border: none; font-size: 1.2rem; cursor: pointer;
		color: var(--text-2, #666); line-height: 1; padding: .2rem;
	}
	.cl-body {
		padding: 1rem 1.25rem; overflow-y: auto; line-height: 1.5;
		font-size: .9rem;
	}
	.cl-body :global(h2),
	.cl-body :global(h3),
	.cl-body :global(h4),
	.cl-body :global(h5) { margin: 1rem 0 .4rem; line-height: 1.25; }
	.cl-body :global(h2) { font-size: 1.05rem; }
	.cl-body :global(h3) { font-size: .98rem; }
	.cl-body :global(h4),
	.cl-body :global(h5) { font-size: .9rem; }
	.cl-body :global(p) { margin: .4rem 0; }
	.cl-body :global(ul),
	.cl-body :global(ol) { margin: .4rem 0; padding-left: 1.3rem; }
	.cl-body :global(li) { margin: .2rem 0; }
	.cl-body :global(code) {
		background: var(--surface-2, rgba(0,0,0,.06));
		padding: .1rem .35rem; border-radius: 4px; font-size: .85em;
	}
	.cl-body :global(a) { color: var(--color-primary, #E23D28); }
	.cl-footer {
		display: flex; justify-content: space-between; align-items: center;
		gap: 1rem; padding: .85rem 1.25rem;
		border-top: 1px solid var(--border, rgba(0,0,0,.1));
	}
	.cl-link { font-size: .82rem; color: var(--text-2, #666); text-decoration: none; }
	.cl-link:hover { text-decoration: underline; }
	.cl-ok {
		background: var(--color-primary, #E23D28); color: #fff; border: none;
		border-radius: 8px; padding: .5rem 1.1rem; font-weight: 600; cursor: pointer;
		font-size: .9rem;
	}
	.cl-ok:hover { background: var(--color-primary-hover, #c43525); }
</style>
