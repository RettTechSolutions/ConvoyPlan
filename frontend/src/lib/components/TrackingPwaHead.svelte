<!--
  Bindet das eigenständige Tracking-Manifest sowie die iOS-Meta-Tags ein.
  Wird auf allen /track-Seiten verwendet, damit ein „Zur App / Zum Home-Bildschirm"
  eine separate „Tracking"-App mit Start auf /track (ID-Abfrage) erzeugt — getrennt
  von der Haupt-App ConvoyPlan.
-->
<svelte:head>
	<link rel="manifest" href="/tracking.webmanifest" />
	<meta name="apple-mobile-web-app-capable" content="yes" />
	<meta name="mobile-web-app-capable" content="yes" />
	<meta name="apple-mobile-web-app-title" content="Tracking" />
	<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
	<meta name="theme-color" content="#1a2744" />
	<link rel="apple-touch-icon" href="/icons/icon-192.png" />
</svelte:head>
