/**
 * Der Marschstatus eines Konvois, zusammengefasst und je Fahrzeug.
 *
 * Gehört zu `konvoi_status`. Die Zusammenfassung steht oben, weil unterwegs
 * zuerst „wie viele sind noch nicht da" gefragt wird und erst danach „wer".
 */
window.CONVOYPLAN_ZEICHNEN = function (d, w) {
  var fahrzeuge = d.fahrzeuge || [];
  var zusammenfassung = d.zusammenfassung || {};

  var kopf =
    '<div class="cp-kopf"><span class="cp-titel">' + w.esc(d.konvoi) + '</span>' +
    '<span class="cp-marke ' + w.konvoiKlasse(d.konvoi_status) + '">' +
    w.esc(w.konvoiStatus(d.konvoi_status)) + '</span></div>';

  var schluessel = Object.keys(zusammenfassung);
  var kacheln = schluessel.length
    ? '<div class="cp-gitter">' + schluessel.map(function (k) {
        return '<div class="cp-kennzahl"><b>' + w.esc(zusammenfassung[k]) + '</b>' +
          '<span class="cp-klein cp-schwach">' + w.esc(bezeichnung(k)) + '</span></div>';
      }).join('') + '</div>'
    : '';

  // Ausfälle und technische Halte zuerst: was klemmt, gehört nach oben.
  var sortiert = fahrzeuge.slice().sort(function (a, b) {
    return gewicht(b.status) - gewicht(a.status);
  });

  var tabelle = sortiert.length
    ? '<table class="cp"><thead><tr><th>Pos.</th><th>Fahrzeug</th><th>Status</th>' +
      '<th>seit</th><th>Notiz</th></tr></thead><tbody>' +
      sortiert.map(function (f) {
        return '<tr><td>' + w.esc(f.position != null ? f.position + 1 : '—') + '</td>' +
          '<td>' + w.esc(f.funkrufname || f.name || '—') + '</td>' +
          '<td><span class="cp-marke ' + fahrzeugKlasse(f.status) + '">' +
          w.esc(bezeichnung(f.status)) + '</span></td>' +
          '<td class="cp-klein cp-schwach">' + w.esc(w.zeitpunkt(f.status_seit) || '—') + '</td>' +
          '<td class="cp-klein">' + w.esc(f.status_notiz || '') + '</td></tr>';
      }).join('') + '</tbody></table>'
    : '<p class="cp-schwach cp-klein">Diesem Konvoi ist noch kein Fahrzeug zugeordnet.</p>';

  return '<div class="cp-karte">' + kopf + kacheln + tabelle + '</div>';
};

function bezeichnung(wert) {
  return {
    planned: 'Geplant', en_route: 'Unterwegs', arrived: 'Angekommen',
    technical_halt: 'Technischer Halt', breakdown: 'Ausgefallen'
  }[wert] || wert || '—';
}

function fahrzeugKlasse(wert) {
  return {
    arrived: 'gut', en_route: 'gut',
    technical_halt: 'warn', breakdown: 'aus'
  }[wert] || '';
}

function gewicht(wert) {
  return { breakdown: 3, technical_halt: 2, planned: 1 }[wert] || 0;
}
