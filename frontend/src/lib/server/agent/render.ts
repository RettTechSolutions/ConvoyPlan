/**
 * Ein kleiner Markdown-Renderer für die Informationsseiten.
 *
 * Warum nicht `marked` oder `markdown-it`: die Eingabe kommt ausschließlich aus
 * `documents.ts`, also aus diesem Repository. Es ist eine bekannte, enge
 * Teilmenge — Überschriften, Absätze, Listen, Tabellen, Links, Code, fett —
 * und dafür lohnt keine Abhängigkeit, die mitgepflegt, mitgescannt und
 * mitaktualisiert werden will.
 *
 * Der Zweck ist die Deckungsgleichheit: `/about` und `/about.md` entstehen aus
 * derselben Quelle, und damit kann die HTML-Fassung nicht von der Fassung
 * abweichen, die ein Agent über `rel="alternate"` angeboten bekommt.
 *
 * Alles wird escaped, bevor Inline-Auszeichnung angewendet wird. Fremde
 * Eingaben landen hier zwar nicht, aber das ist eine Eigenschaft der Aufrufer
 * und keine des Renderers — und Eigenschaften der Aufrufer ändern sich.
 */

const escapeHtml = (s: string): string =>
	s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** Inline-Auszeichnung auf bereits escapetem Text. */
function inline(text: string): string {
	let out = escapeHtml(text);
	// Code zuerst, damit darin nichts weiter ausgezeichnet wird.
	out = out.replace(/`([^`]+)`/g, (_m, code: string) => `<code>${code}</code>`);
	out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label: string, href: string) => {
		const external = /^https?:\/\//i.test(href) && !href.includes('%%SELF%%');
		const rel = external ? ' rel="noopener"' : '';
		return `<a href="${href}"${rel}>${label}</a>`;
	});
	out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
	// Nackte URLs verlinken, damit ein Kontakt-Link auch klickbar ist.
	out = out.replace(
		/(^|[\s(])(https?:\/\/[^\s<)]+)/g,
		(_m, pre: string, url: string) => `${pre}<a href="${url}" rel="noopener">${url}</a>`
	);
	return out;
}

const slug = (text: string): string =>
	text
		.toLowerCase()
		.replace(/[äÄ]/g, 'ae')
		.replace(/[öÖ]/g, 'oe')
		.replace(/[üÜ]/g, 'ue')
		.replace(/ß/g, 'ss')
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-|-$/g, '');

interface Rendered {
	/** Der Titel aus der einzigen H1 des Dokuments. */
	readonly title: string;
	/** Der Rumpf ohne die H1 — die rendert die Seite selbst. */
	readonly html: string;
	/** Erster Absatz, als Kurzbeschreibung für `<meta name="description">`. */
	readonly lead: string;
}

const splitRow = (line: string): string[] =>
	line
		.replace(/^\|/, '')
		.replace(/\|$/, '')
		.split('|')
		.map((c) => c.trim());

export function renderMarkdown(source: string): Rendered {
	const lines = source.split('\n');
	const out: string[] = [];
	let title = '';
	let lead = '';
	let paragraph: string[] = [];
	let list: string[] | null = null;

	const flushParagraph = () => {
		if (paragraph.length === 0) return;
		const text = paragraph.join(' ');
		if (!lead) lead = text.replace(/[`*[\]]/g, '').replace(/\(https?:\/\/[^)]+\)/g, '').trim();
		out.push(`<p>${inline(text)}</p>`);
		paragraph = [];
	};
	const flushList = () => {
		if (!list) return;
		out.push(`<ul>${list.map((i) => `<li>${inline(i)}</li>`).join('')}</ul>`);
		list = null;
	};
	const flushAll = () => {
		flushParagraph();
		flushList();
	};

	for (let i = 0; i < lines.length; i += 1) {
		const raw = lines[i];
		const lineText = raw.trimEnd();

		if (lineText.trim() === '') {
			flushAll();
			continue;
		}

		// Fenced code
		if (lineText.startsWith('```')) {
			flushAll();
			const buf: string[] = [];
			i += 1;
			while (i < lines.length && !lines[i].startsWith('```')) {
				buf.push(lines[i]);
				i += 1;
			}
			out.push(`<pre><code>${escapeHtml(buf.join('\n'))}</code></pre>`);
			continue;
		}

		// Tabelle: Kopfzeile, Trennzeile, dann Datenzeilen.
		if (lineText.startsWith('|') && (lines[i + 1] ?? '').trim().startsWith('|--')) {
			flushAll();
			const head = splitRow(lineText);
			i += 2;
			const body: string[][] = [];
			while (i < lines.length && lines[i].trim().startsWith('|')) {
				body.push(splitRow(lines[i].trim()));
				i += 1;
			}
			i -= 1;
			out.push(
				`<div class="table-wrap"><table><thead><tr>${head
					.map((c) => `<th>${inline(c)}</th>`)
					.join('')}</tr></thead><tbody>${body
					.map((row) => `<tr>${row.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`)
					.join('')}</tbody></table></div>`
			);
			continue;
		}

		const heading = /^(#{1,4})\s+(.*)$/.exec(lineText);
		if (heading) {
			flushAll();
			const level = heading[1].length;
			const text = heading[2].trim();
			if (level === 1 && !title) {
				title = text.replace(/[`*]/g, '');
				continue;
			}
			out.push(`<h${level} id="${slug(text)}">${inline(text)}</h${level}>`);
			continue;
		}

		const bullet = /^[-*]\s+(.*)$/.exec(lineText);
		if (bullet) {
			flushParagraph();
			(list ??= []).push(bullet[1]);
			continue;
		}

		const numbered = /^\d+\.\s+(.*)$/.exec(lineText);
		if (numbered) {
			flushParagraph();
			(list ??= []).push(numbered[1]);
			continue;
		}

		if (lineText.trim() === '---') {
			flushAll();
			out.push('<hr />');
			continue;
		}

		flushList();
		paragraph.push(lineText.trim());
	}
	flushAll();

	return { title, html: out.join('\n'), lead: lead.slice(0, 300) };
}
