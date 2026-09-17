/**
 * Ein Konvoi mit Marschbefehl und Fahrzeugen in Marschordnung.
 *
 * Gehört zu `konvoi_details`. Die Fahrzeugtabelle steht bewusst in der
 * gespeicherten Reihenfolge und zeigt die Marschposition mit: in einer
 * Kolonne ist „wer fährt wo" die Angabe, um die es geht.
 */
window.CONVOYPLAN_ZEICHNEN = function (d, w) {
  var fahrzeuge = d.fahrzeuge || [];
  var mb = d.marschbefehl || {};

  var kopf =
    '<div class="cp-kopf">' +
    '<span class="cp-titel">' + w.esc(d.name) + '</span>' +
    '<span class="cp-marke ' + klasseFuer(d.status) + '">' + w.esc(status(d.status)) + '</span>' +
    '</div>';

  var kennzahlen =
    '<div class="cp-gitter">' +
    kennzahl(fahrzeuge.length, fahrzeuge.length === 1 ? 'Fahrzeug' : 'Fahrzeuge') +
    kennzahl(d.wegpunkte_anzahl || 0, 'Wegpunkte') +
    kennzahl(w.zeitpunkt(d.start_zeit) || '—', 'Abmarsch') +
    (d.marschform ? kennzahl(marschform(d.marschform), 'Marschform') : '') +
    '</div>';

  // Nur die Abschnitte zeigen, die auch gefüllt sind — ein Marschbefehl mit
  // sieben leeren Zeilen sieht nach einem Fehler aus, nicht nach einem
  // Konvoi, der noch in Arbeit ist.
  var felder = [
    ['Lage', mb.lage], ['Auftrag', mb.auftrag],
    ['Ablaufpunkt', mb.ablaufpunkt], ['Ablaufzeit', w.zeitpunkt(mb.ablaufzeit)],
    ['Ablaufführer', mb.ablauffuehrer], ['Versorgung', mb.versorgung],
    ['Funkgruppe', mb.funkgruppe], ['Anlagen', mb.anlagen]
  ].filter(function (f) { return f[1]; });

  var befehl = felder.length
    ? '<dl class="cp">' + felder.map(function (f) {
        return '<dt>' + w.esc(f[0]) + '</dt><dd>' + w.esc(f[1]) + '</dd>';
      }).join('') + '</dl>'
    : '<p class="cp-schwach cp-klein">Zum Marschbefehl ist noch nichts hinterlegt.</p>';

  var tabelle = fahrzeuge.length
    ? '<table class="cp"><thead><tr><th>Pos.</th><th>Fahrzeug</th><th>Funkrufname</th>' +
      '<th>Kennzeichen</th><th>Sonderfunktion</th></tr></thead><tbody>' +
      fahrzeuge.map(function (f) {
        return '<tr><td>' + w.esc(f.position != null ? f.position + 1 : '—') + '</td>' +
          '<td>' + w.esc(f.name || '—') + '</td>' +
          '<td>' + w.esc(f.funkrufname || '—') + '</td>' +
          '<td>' + w.esc(f.kennzeichen || '—') + '</td>' +
          '<td>' + w.esc(sonderfunktion(f.sonderfunktion)) + '</td></tr>';
      }).join('') + '</tbody></table>'
    : '<p class="cp-schwach cp-klein">Diesem Konvoi ist noch kein Fahrzeug zugeordnet.</p>';

  return '<div class="cp-karte">' + kopf + kennzahlen + befehl + tabelle + '</div>';
};

function kennzahl(wert, beschriftung) {
  return '<div class="cp-kennzahl"><b>' + wert + '</b><span class="cp-klein cp-schwach">' +
    beschriftung + '</span></div>';
}

function status(wert) {
  return { planning: 'In Planung', active: 'Läuft', completed: 'Abgeschlossen' }[wert] || wert || '—';
}

function klasseFuer(wert) {
  return { active: 'gut', completed: '' }[wert] || 'warn';
}

function marschform(wert) {
  return {
    geschlossener_verband: 'Geschlossen',
    einzelgruppen: 'Einzelgruppen',
    individuell: 'Individuell'
  }[wert] || wert;
}

function sonderfunktion(wert) {
  if (!wert) return '—';
  return {
    spitzenführer: 'Spitzenführer', schließender: 'Schließender',
    sanitaet: 'Sanität', ablaufführer: 'Ablaufführer'
  }[wert] || wert;
}
