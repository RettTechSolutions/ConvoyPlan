/**
 * Die Konvois einer Organisation als Liste.
 *
 * Gehört zu `konvois_auflisten`. Zeigt je Konvoi das, wonach im Gespräch
 * als Nächstes gefragt wird — Startzeit, Umfang, Status — und nicht die ID:
 * die braucht das Modell für den nächsten Aufruf, der Mensch nicht.
 */
window.CONVOYPLAN_ZEICHNEN = function (d, w) {
  var konvois = d.konvois || [];
  var kopf =
    '<div class="cp-kopf"><span class="cp-titel">' + w.esc(d.organisation || 'Konvois') +
    '</span><span class="cp-schwach cp-klein">' + konvois.length +
    (konvois.length === 1 ? ' Konvoi' : ' Konvois') + '</span></div>';

  if (!konvois.length) {
    return kopf + '<p class="cp-schwach cp-klein">Keine Konvois gefunden.</p>';
  }

  var zeilen = konvois.map(function (k) {
    var start = w.zeitpunkt(k.start_zeit);
    var angaben = [];
    angaben.push('<span class="cp-marke ' + klasseFuer(k.status) + '">' + w.esc(status(k.status)) + '</span>');
    if (start) angaben.push('<span class="cp-klein">Abmarsch ' + w.esc(start) + '</span>');
    angaben.push('<span class="cp-klein cp-schwach">' + (k.fahrzeuge_anzahl || 0) + ' Fahrzeuge</span>');
    angaben.push('<span class="cp-klein cp-schwach">' + (k.wegpunkte_anzahl || 0) + ' Wegpunkte</span>');
    if (k.ist_unterkonvoi) angaben.push('<span class="cp-klein cp-schwach">Teilkolonne</span>');

    return '<div class="cp-karte"><div class="cp-titel">' + w.esc(k.name) + '</div>' +
      '<div class="cp-zeile">' + angaben.join('') + '</div></div>';
  }).join('');

  var hinweis = d.hinweis
    ? '<p class="cp-schwach cp-klein">' + w.esc(d.hinweis) + '</p>'
    : '';

  return kopf + '<div style="margin-top:10px">' + zeilen + '</div>' + hinweis;
};

function status(wert) {
  return { planning: 'In Planung', active: 'Läuft', completed: 'Abgeschlossen' }[wert] || wert || '—';
}

function klasseFuer(wert) {
  return { active: 'gut', completed: '' }[wert] || 'warn';
}
