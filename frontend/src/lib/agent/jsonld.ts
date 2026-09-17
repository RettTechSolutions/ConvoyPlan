/**
 * JSON-LD für die Startseite.
 *
 * Ein `@graph` statt mehrerer `<script>`-Blöcke: die Knoten verweisen über
 * `@id` aufeinander, sodass ein Parser Organisation, Website und Software als
 * *eine* Entität erkennt statt als drei zufällig gleichnamige.
 *
 * Alle URLs entstehen aus dem `origin` der Anfrage — eine Instanz unter
 * feuerwehr.example darf sich nicht als convoyplan.de ausgeben.
 */
import { PRODUCT, SAME_AS, FAQ, PLANS, FEATURES } from './facts';

export function buildJsonLd(origin: string): string {
	const base = origin.replace(/\/$/, '');
	const org = `${base}/#organization`;
	const site = `${base}/#website`;
	const app = `${base}/#software`;

	const graph: Record<string, unknown>[] = [
		{
			'@type': 'Organization',
			'@id': org,
			name: PRODUCT.legalName,
			legalName: PRODUCT.legalName,
			url: PRODUCT.website,
			description: `Hersteller von ${PRODUCT.name} — ${PRODUCT.tagline}`,
			founder: { '@type': 'Person', name: PRODUCT.founder },
			logo: { '@type': 'ImageObject', url: `${base}/logo/light/LogoHorinzontal.png` },
			sameAs: SAME_AS,
			address: { '@type': 'PostalAddress', addressCountry: PRODUCT.country },
			contactPoint: [
				{
					'@type': 'ContactPoint',
					contactType: 'sales',
					email: PRODUCT.email,
					availableLanguage: ['de', 'en'],
					areaServed: 'DE'
				},
				{
					'@type': 'ContactPoint',
					contactType: 'technical support',
					email: PRODUCT.email,
					url: `${PRODUCT.repository}/issues`,
					availableLanguage: ['de', 'en']
				},
				{
					'@type': 'ContactPoint',
					contactType: 'security',
					email: PRODUCT.email,
					url: `${PRODUCT.repository}/blob/main/SECURITY.md`,
					availableLanguage: ['de', 'en']
				}
			]
		},
		{
			'@type': 'WebSite',
			'@id': site,
			url: `${base}/`,
			name: PRODUCT.name,
			inLanguage: PRODUCT.inLanguage,
			publisher: { '@id': org },
			about: { '@id': app }
		},
		{
			'@type': 'SoftwareApplication',
			'@id': app,
			name: PRODUCT.name,
			alternateName: 'Convoy Plan',
			applicationCategory: PRODUCT.category,
			applicationSubCategory: 'Konvoi- und Marschplanung',
			operatingSystem: PRODUCT.operatingSystem,
			url: `${base}/`,
			sameAs: SAME_AS,
			description: PRODUCT.description,
			inLanguage: PRODUCT.inLanguage,
			license: PRODUCT.licenseUrl,
			isAccessibleForFree: true,
			publisher: { '@id': org },
			author: { '@id': org },
			softwareHelp: { '@type': 'CreativeWork', url: PRODUCT.wiki },
			featureList: FEATURES.map((f) => f.title),
			offers: PLANS.map((plan) => ({
				'@type': 'Offer',
				name: plan.name,
				description: plan.summary,
				url: `${base}/pricing`,
				priceCurrency: plan.currency,
				...(plan.priceNumeric === null
					? { priceSpecification: { '@type': 'PriceSpecification', priceCurrency: plan.currency } }
					: { price: plan.priceNumeric }),
				availability: 'https://schema.org/InStock'
			}))
		},
		{
			'@type': 'Service',
			'@id': `${base}/#service`,
			name: `${PRODUCT.name} Marschplanung`,
			serviceType: 'Konvoi- und Marschplanung für Einsatzorganisationen',
			provider: { '@id': org },
			areaServed: [
				{ '@type': 'Country', name: 'Deutschland' },
				{ '@type': 'Country', name: 'Österreich' },
				{ '@type': 'Country', name: 'Schweiz' },
				{ '@type': 'Country', name: 'Liechtenstein' }
			],
			availableChannel: {
				'@type': 'ServiceChannel',
				serviceUrl: `${base}/`,
				name: 'Web-Anwendung'
			}
		},
		{
			'@type': 'WebAPI',
			'@id': `${base}/#api`,
			name: 'ConvoyPlan REST-API',
			description:
				'REST-API für Konvois, Fahrzeuge, Wegpunkte, Routen und Live-Positionen. Authentifizierung per Bearer-JWT oder API-Key.',
			documentation: `${base}/developers`,
			termsOfService: PRODUCT.licenseUrl,
			provider: { '@id': org }
		},
		{
			'@type': 'FAQPage',
			'@id': `${base}/#faq`,
			inLanguage: PRODUCT.inLanguage,
			mainEntity: FAQ.map((item) => ({
				'@type': 'Question',
				name: item.q,
				acceptedAnswer: { '@type': 'Answer', text: item.a }
			}))
		},
		{
			'@type': 'BreadcrumbList',
			'@id': `${base}/#breadcrumb`,
			itemListElement: [
				{ '@type': 'ListItem', position: 1, name: 'Start', item: `${base}/` },
				{ '@type': 'ListItem', position: 2, name: 'Über ConvoyPlan', item: `${base}/about` },
				{ '@type': 'ListItem', position: 3, name: 'Preise', item: `${base}/pricing` },
				{ '@type': 'ListItem', position: 4, name: 'Entwickler', item: `${base}/developers` }
			]
		}
	];

	return JSON.stringify({ '@context': 'https://schema.org', '@graph': graph });
}
