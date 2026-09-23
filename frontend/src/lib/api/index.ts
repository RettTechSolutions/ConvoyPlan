import { api, uploadFile, downloadFile, getStreamTicket, type Sitzung } from './client';
import type { Geometry } from 'geojson';

export interface Point { lat: number; lon: number }

// 'bundesstrasse' / 'landstrasse' are legacy values still present on older
// convoys; the backend maps them to 'standard'.
export type RoadPreference = 'standard' | 'schnell' | 'kuerzeste' | 'bundesstrasse' | 'landstrasse';

export type Propulsion = 'combustion' | 'electric';

export interface Vehicle {
	id: string; name: string; callsign: string | null; license_plate: string | null;
	height_cm: number | null; weight_kg: number | null; length_cm: number | null; convoy_role: string | null;
	propulsion: Propulsion;
	tank_capacity_l: number | null; fuel_consumption_l100km: number | null; current_fuel_l: number | null;
	battery_capacity_kwh: number | null; consumption_kwh_100km: number | null; current_charge_kwh: number | null;
	// Regelbesatzung (siehe $lib/tracking/staerke): mit wem das Fahrzeug
	// üblicherweise ausrückt. Beim Hinzufügen zu einem Konvoi übernimmt das
	// Backend sie als dessen Sollstärke; null heißt „nicht angegeben".
	staerke_soll_fuehrer: number | null;
	staerke_soll_unterfuehrer: number | null;
	staerke_soll_mannschaften: number | null;
	order_index: number; range_km: number | null; range_uses_defaults: boolean;
}

export interface FuelStopPosition { lat: number; lon: number; }
export interface VehicleRangeInfo { name: string; callsign: string | null; range_km: number; using_defaults: boolean; propulsion?: Propulsion; }
export type HaltKind = 'tech' | 'break' | 'daily_rest';
export interface DurationHalt {
	stop_km: number;
	stop_position: FuelStopPosition | null;
	duration_min: number;
	kind: HaltKind;
	is_rest: boolean;
	after_drive_s: number;
	covers_break: boolean;
}
export interface FuelAnalysis {
	vehicles_with_range: VehicleRangeInfo[];
	min_range_km: number | null;
	route_distance_km: number;
	fuel_stop_needed: boolean;
	fuel_stop_km: number | null;
	fuel_stop_position: FuelStopPosition | null;
	limiting_vehicle: string | null;
	limiting_propulsion?: Propulsion;
	has_default_values: boolean;
	vehicles_without_data: number;
	recommended_stop_duration_min: number | null;
	duration_halt_needed: boolean;
	duration_halts: DurationHalt[];
	rest_needed: boolean;
}

export interface FuelStation {
	osm_id: number; lat: number; lon: number;
	name: string; brand: string | null; operator: string | null;
	opening_hours: string | null; distance_m: number;
}

export interface Waypoint {
	id: string; name: string; type: string;
	lat: number | null; lon: number | null;
	planned_arrival: string | null; planned_departure: string | null;
	hold_duration_min: number; halt_purpose: string | null;
	notes: string | null; order_index: number;
	// Von der Anwendung vorgeschlagen und noch nicht einsortiert — die nächste
	// Routenberechnung gibt ihm seinen Platz entlang der Route.
	pending_placement?: boolean;
}

export interface ConvoyVehicleItem {
	vehicle: Vehicle; position: number; vehicle_status: string;
	status_level: string | null; status_note: string | null; status_changed_at: string | null;
	sonderfunktion: string | null; mobile_phone: string | null;
	// Mannschaftsstärke (siehe $lib/tracking/staerke): null heißt „nicht
	// angegeben", 0 heißt „niemand" — die beiden nie gleichsetzen.
	staerke_soll_fuehrer: number | null;
	staerke_soll_unterfuehrer: number | null;
	staerke_soll_mannschaften: number | null;
	staerke_ist_fuehrer: number | null;
	staerke_ist_unterfuehrer: number | null;
	staerke_ist_mannschaften: number | null;
	staerke_gemeldet_at: string | null;
	// Betriebsstofflage (siehe $lib/tracking/betriebsstoff) — null heißt
	// „nicht gemeldet", ein Füllstand 0 heißt „leer".
	betriebsstoff_verbrauch?: number | null;
	betriebsstoff_tank?: number | null;
	betriebsstoff_fuellstand?: number | null;
	betriebsstoff_gemeldet_at?: string | null;
}

export interface Convoy {
	id: string; name: string; organization: string | null;
	organization_id: string | null; parent_convoy_id: string | null;
	start_time: string | null; speed_urban_kmh: number; speed_rural_kmh: number;
	road_preference: RoadPreference;
	spacing_urban_m: number;
	spacing_rural_m: number;
	spacing_motorway_m: number;
	status: string; share_token: string; created_at: string;
	start_point: Point | null; end_point: Point | null;
	convoy_vehicles: ConvoyVehicleItem[]; waypoints: Waypoint[];
	lage: string | null; auftrag: string | null; marschform: string | null;
	ablaufpunkt: string | null; ablaufzeit: string | null; ablaufführer: string | null;
	versorgung: string | null; funkgruppe: string | null; anlagen: string | null;
}

export interface KanalwechselEntry {
	km: number;
	lat: number;
	lon: number;
	leitstelle_id: string;
	leitstelle_name: string;
	anrufgruppe: string;
	/**
	 * "convoy_anmeldung" = Anmeldung des Verbands bei der Start-Leitstelle,
	 * "anmelden" = Wechsel zur neuen Leitstelle, "abmelden" = Abmeldung bei
	 * der alten (fehlt bei alten Routen).
	 */
	typ?: 'anmelden' | 'abmelden' | 'convoy_anmeldung';
	/** Weitere hinterlegte Funkgruppen der Leitstelle. */
	zusatz_kanaele?: { name?: string; kanal?: string }[];
}

export interface RouteResult {
	id: string; convoy_id: string; distance_m: number | null; duration_s: number | null;
	routing_params: Record<string, unknown> | null; geojson: Geometry | null;
	fuel_analysis: FuelAnalysis | null;
	kanalwechsel?: KanalwechselEntry[];
	/** Abmarschzeit (ISO), auf derselben Zeitbasis wie die Wegpunkt-Zeiten. */
	planned_departure?: string | null;
	/** Geplante Ankunft am Ziel (ISO); Abmarsch + Fahrzeit + Haltezeiten. */
	planned_arrival?: string | null;
}

export interface Organization {
	id: string; name: string; description: string | null;
	member_count: number; my_role: string;
}

export interface OrgMember {
	user_id: string; email: string; role: string;
	first_name: string | null; last_name: string | null;
}

export interface VehiclePosition {
	vehicle_id: string; lat: number; lon: number;
	speed_kmh: number | null; heading: number | null; recorded_at: string;
}

export interface WeatherCurrent {
	temp_c: number; windspeed_kmh: number; condition: string; is_day: boolean;
}
export interface WeatherForecastItem {
	time: string; temp_c: number; precip_pct: number; condition: string;
}
export interface WeatherResponse {
	current: WeatherCurrent;
	hourly_forecast: WeatherForecastItem[];
}

export interface ServiceCheck {
	status: 'ok' | 'error' | 'unknown';
	latency_ms: number | null;
	checked_at: string | null;
}

export interface StatusResponse {
	checked_at: string;
	backend: 'ok' | 'error';
	database: 'ok' | 'error';
	graphhopper: 'ok' | 'building' | 'offline';
	graphhopper_bbox: number[] | null;
	weather_api: ServiceCheck;
	overpass_api: ServiceCheck;
	autobahn_api: ServiceCheck;
	traffic_flow?: { provider: string | null };
}

// Öffentliche Statusseite: grobkörnig und ohne Betriebsinterna (keine Latenzen,
// keine Anbieter, keine Versionen) — siehe GET /api/status/public.
export type PublicComponentState = 'operational' | 'degraded' | 'down' | 'unknown';

export interface PublicStatusComponent {
	key: string;
	name: string;
	description: string;
	state: PublicComponentState;
}

export interface PublicStatusResponse {
	checked_at: string;
	overall: PublicComponentState;
	components: PublicStatusComponent[];
}

export interface LoginResult {
	access_token: string | null;
	token_type: string;
	mfa_required: boolean;
	mfa_token: string | null;
}

// Auth

/** Kontaktangabe beim Demo-Start — die Adresse ist Pflicht, der Name nicht. */
export interface DemoContact {
	email: string;
	first_name?: string;
	last_name?: string;
}

export interface DemoSessionResult {
    access_token: string;
    token_type: string;
    org_slug: string;
    expires_at: string;
    /** true = bestehende Sitzung fortgesetzt, keine neue angelegt. */
    resumed?: boolean;
}

export interface MeResult {
	user_id: string;
	email: string;
	is_superadmin: boolean;
	org_id: string | null;
	org_slug: string | null;
	org_name: string | null;
	role: string | null;
	is_demo: boolean;
}

export const authApi = {
	/**
	 * Wer gerade angemeldet ist — die Auskunft des Servers.
	 *
	 * Ersetzt das frühere Dekodieren des JWT im Browser. Wirft bei fehlender
	 * oder abgelaufener Sitzung (401); genau daran erkennen die Stores, dass
	 * zur Anmeldung geschickt werden muss.
	 */
	me: (sitzung: Sitzung = 'seite') => api.get<MeResult>('/api/auth/me', sitzung),
	/** Die Sitzung serverseitig beenden — ein HttpOnly-Cookie kann sich das
	 *  Portal nicht selbst wegnehmen. */
	logout: (sitzung: Sitzung = 'seite') =>
		api.post<{ status: string }>('/api/auth/logout', {}, sitzung),
	register: (email: string, password: string) => api.post('/api/auth/register', { email, password }),
	login: (email: string, password: string) =>
		api.post<LoginResult>('/api/auth/login', { email, password }),
	mfaVerify: (mfa_token: string, code: string) =>
		api.post<LoginResult>('/api/auth/mfa/verify', { mfa_token, code }),
	changePassword: (current_password: string, new_password: string) =>
		api.post<{ status: string; access_token?: string }>('/api/auth/password', { current_password, new_password }),
	requestPasswordReset: (email: string, org_slug?: string) =>
		api.post<{ status: string }>('/api/auth/password-reset', { email, org_slug }),
	createDemoSession: (contact: DemoContact) =>
		api.post<DemoSessionResult>('/api/auth/demo-session', contact),
	unsubscribeDemoFollowup: (token: string) =>
		api.post<{ status: string }>('/api/auth/demo-followup/unsubscribe', { token }),
	demoStatus: () => api.get<{ enabled: boolean; session_hours: number }>('/api/auth/demo-status'),
	demoSessionInfo: () => api.get<{ expires_at: string }>('/api/auth/demo-session/info'),
};

export const mfaApi = {
	status: () => api.get<{ mfa_enabled: boolean }>('/api/auth/mfa/status'),
	setup: () => api.post<{ secret: string; provisioning_uri: string }>('/api/auth/mfa/setup', {}),
	confirm: (code: string) => api.post<{ status: string }>('/api/auth/mfa/confirm', { code }),
	disable: (code: string) => api.post<{ status: string }>('/api/auth/mfa/disable', { code }),
};

// Vehicles
export const vehiclesApi = {
	list: () => api.get<Vehicle[]>('/api/vehicles/'),
	create: (data: Partial<Vehicle>) => api.post<Vehicle>('/api/vehicles/', data),
	update: (id: string, data: Partial<Vehicle>) => api.put<Vehicle>(`/api/vehicles/${id}`, data),
	reorder: (items: { id: string; order_index: number }[]) => api.patch('/api/vehicles/reorder', items),
	delete: (id: string) => api.delete(`/api/vehicles/${id}`),
};

// Convoys
export const convoysApi = {
	list: () => api.get<Convoy[]>('/api/convoys/'),
	create: (data: Record<string, unknown>) => api.post<Convoy>('/api/convoys/', data),
	get: (id: string) => api.get<Convoy>(`/api/convoys/${id}`),
	update: (id: string, data: Record<string, unknown>) => api.put<Convoy>(`/api/convoys/${id}`, data),
	delete: (id: string) => api.delete(`/api/convoys/${id}`),
	addVehicle: (id: string, vehicleId: string, position: number, sonderfunktion?: string, mobile_phone?: string) =>
		api.post(`/api/convoys/${id}/vehicles`, { vehicle_id: vehicleId, position, sonderfunktion, mobile_phone }),
	/** Planungsangaben eines Fahrzeugs im Verband — nur genannte Felder ändern sich. */
	updateVehicleInConvoy: (
		id: string,
		vehicleId: string,
		data: {
			sonderfunktion?: string | null;
			mobile_phone?: string | null;
			staerke_soll_fuehrer?: number | null;
			staerke_soll_unterfuehrer?: number | null;
			staerke_soll_mannschaften?: number | null;
		},
	) => api.patch(`/api/convoys/${id}/vehicles/${vehicleId}`, data),
	removeVehicle: (id: string, vehicleId: string) =>
		api.delete(`/api/convoys/${id}/vehicles/${vehicleId}`),
	reorderVehicles: (id: string, items: { vehicle_id: string; position: number }[]) =>
		api.patch<Convoy>(`/api/convoys/${id}/vehicles/reorder`, items),
	createWaypoint: (id: string, data: Record<string, unknown>) =>
		api.post<Waypoint>(`/api/convoys/${id}/waypoints`, data),
	updateWaypoint: (id: string, wpId: string, data: Record<string, unknown>) =>
		api.put<Waypoint>(`/api/convoys/${id}/waypoints/${wpId}`, data),
	deleteWaypoint: (id: string, wpId: string) =>
		api.delete(`/api/convoys/${id}/waypoints/${wpId}`),
	reorderWaypoints: (id: string, items: { id: string; order_index: number }[]) =>
		api.patch<Waypoint[]>(`/api/convoys/${id}/waypoints/reorder`, items),
	getRoute: (id: string) =>
		api.get<RouteResult | null>(`/api/convoys/${id}/route`),
	calculateRoute: (id: string) =>
		api.post<RouteResult>(`/api/convoys/${id}/calculate-route`, {}),
	findFuelStations: (id: string, lat: number, lon: number, radiusM = 3000) =>
		api.get<FuelStation[]>(`/api/convoys/${id}/fuel-stations?lat=${lat}&lon=${lon}&radius_m=${radiusM}`),
	listSubConvoys: (id: string) => api.get<Convoy[]>(`/api/convoys/${id}/sub-convoys`),
	createSubConvoy: (id: string, data: Record<string, unknown>) =>
		api.post<Convoy>(`/api/convoys/${id}/sub-convoys`, data),
	exportUrl: (id: string, format: 'gpx' | 'json' | 'pdf') =>
		`/api/convoys/${id}/export/${format}`,
	importFile: (id: string, format: 'gpx' | 'geojson', file: File, mode: 'add' | 'replace') =>
		uploadFile<{ waypoints_imported: number; route_stored: boolean }>(
			`/api/convoys/${id}/import/${format}?mode=${mode}`,
			file
		),
};

// V3: Tracking
export const trackingApi = {
	getPositions: (convoyId: string) => api.get<VehiclePosition[]>(`/api/convoys/${convoyId}/positions`),
	updatePosition: (convoyId: string, data: Omit<VehiclePosition, 'recorded_at'>) =>
		api.post(`/api/convoys/${convoyId}/positions`, data),
	updateVehicleStatus: (
		convoyId: string,
		vehicleId: string,
		vehicle_status: string,
		status_level: string | null = null,
		status_note: string | null = null,
	) =>
		api.patch(`/api/convoys/${convoyId}/vehicles/${vehicleId}/status`, {
			vehicle_status,
			status_level,
			status_note,
		}),
	/** Gemeldete Mannschaftsstärke setzen — für die Führung, die eine Funkmeldung nachträgt. */
	updateVehicleStaerke: (
		convoyId: string,
		vehicleId: string,
		staerke: { fuehrer: number; unterfuehrer: number; mannschaften: number },
	) => api.patch<{ status: string; gesamt: number }>(
		`/api/convoys/${convoyId}/vehicles/${vehicleId}/staerke`, staerke,
	),
	/** GPS-Freigabe eines Fahrzeugs beenden (Position löschen). suppress=false beim Selbst-Stopp. */
	clearVehiclePosition: (convoyId: string, vehicleId: string, suppress = true) =>
		api.delete(`/api/convoys/${convoyId}/vehicles/${vehicleId}/position?suppress=${suppress}`),
};

// V2: Organizations
export const orgsApi = {
	list: () => api.get<Organization[]>('/api/organizations/'),
	create: (name: string, description?: string) =>
		api.post<Organization>('/api/organizations/', { name, description }),
	listMembers: (orgId: string) => api.get<OrgMember[]>(`/api/organizations/${orgId}/members`),
	addMember: (orgId: string, email: string, role: string) =>
		api.post(`/api/organizations/${orgId}/members`, { email, role }),
	updateMemberRole: (orgId: string, userId: string, role: string) =>
		api.patch(`/api/organizations/${orgId}/members/${userId}`, { role }),
	removeMember: (orgId: string, userId: string) =>
		api.delete(`/api/organizations/${orgId}/members/${userId}`),
	delete: (orgId: string) => api.delete(`/api/organizations/${orgId}`),
	inviteMember: (orgId: string, email: string, password: string, firstName?: string, lastName?: string) =>
		api.post(`/api/organizations/${orgId}/members/invite`, {
			email, password, first_name: firstName || undefined, last_name: lastName || undefined,
		}),
};

// V3: Wetter
export const weatherApi = {
	get: (lat: number, lon: number) =>
		api.get<WeatherResponse>(`/api/weather/?lat=${lat}&lon=${lon}`),
};

// V3: Status
export const statusApi = {
	get: () => api.get<StatusResponse>('/api/status'),
	// Ohne Anmeldung erreichbar — die Statusseite läuft auch dann noch, wenn
	// gerade niemand eingeloggt ist (oder das Login selbst hakt).
	getPublic: () => api.get<PublicStatusResponse>('/api/status/public'),
};

// V3: Online Users (SSE)
// Passes a short-lived stream ticket as a query param (EventSource cannot set
// headers) so the backend can dedupe by user — reloads/extra tabs don't inflate
// the count — without exposing the long-lived access token in the URL.
export const usersApi = {
	onlineStream: async (): Promise<EventSource> => {
		const ticket = await getStreamTicket();
		const qs = ticket ? `?token=${encodeURIComponent(ticket)}` : '';
		return new EventSource(`/api/users/online${qs}`);
	},
};

// V3: Sperrungen
export const overpassApi = {
	getClosures: (lat: number, lon: number, radiusM = 15000) =>
		api.get<Record<string, unknown>>(`/api/overpass/closures?lat=${lat}&lon=${lon}&radius_m=${radiusM}`),
	// Sperrungen im Korridor entlang der Route (coordinates: GeoJSON [lon, lat])
	getClosuresForRoute: (coordinates: number[][], corridorM = 2000) =>
		api.post<Record<string, unknown>>('/api/overpass/closures/route', {
			coordinates,
			corridor_m: corridorM,
		}),
};

// Live-Verkehrslage (HERE/TomTom) — nur aktiv, wenn eine Installation einen
// eigenen API-Key hinterlegt hat (sonst liefert der Server leere Ergebnisse).
export const trafficApi = {
	flowStatus: () => api.get<{ provider: string | null }>('/api/traffic/flow/status'),
	getFlowForRoute: (coordinates: number[][], corridorM = 1000) =>
		api.post<Record<string, unknown>>('/api/traffic/flow/route', {
			coordinates,
			corridor_m: corridorM,
		}),
};

// Adresssuche (Geocoding) — serverseitig proxied. Nutzt HERE, wenn ein Key
// hinterlegt ist, sonst Photon. Der Aufruf erfolgt aus LocationSearch.svelte
// direkt per fetch (mit AbortController fürs Debouncing), daher hier nur die
// Typen als gemeinsame Referenz.
export interface GeocodeResult {
	lat: number;
	lon: number;
	primary: string;
	secondary: string;
}
export interface GeocodeResponse {
	provider: 'here' | 'photon' | null;
	results: GeocodeResult[];
}

// Public share
export const shareApi = {
	get: (token: string) => api.get<{
		name: string; organization: string | null; start_time: string | null;
		waypoints: Waypoint[]; geojson: Geometry | null;
	}>(`/api/convoys/share/${token}`),
};

// ── Public tracking share-links ──────────────────────────────────────────────

export type ShareLinkPasswordMode = 'none' | 'generate' | 'set';
/** Link capability: read-only viewer or a driver that may send GPS / status. */
export type ShareLinkScope = 'track' | 'driver';

export interface ShareLink {
	id: string;
	slug: string;
	scope: string;
	requires_password: boolean;
	created_at: string;
	last_accessed_at: string | null;
	access_count: number;
	revoked: boolean;
	url: string;
}

export interface ShareLinkCreated extends ShareLink {
	password_plain: string | null;
}

export const shareLinksApi = {
	list: (convoyId: string) =>
		api.get<ShareLink[]>(`/api/convoys/${convoyId}/share-links`),
	create: (convoyId: string, body: { password_mode: ShareLinkPasswordMode; password?: string | null; scope?: ShareLinkScope }) =>
		api.post<ShareLinkCreated>(`/api/convoys/${convoyId}/share-links`, body),
	revoke: (convoyId: string, linkId: string) =>
		api.delete(`/api/convoys/${convoyId}/share-links/${linkId}`),
};

export interface TrackVehicle {
	id: string; name: string; callsign: string | null;
	sonderfunktion: string | null; vehicle_status: string | null; position: number;
	// Mannschaftsstärke: Soll aus der Planung, Ist aus der Meldung unterwegs.
	staerke_soll_fuehrer: number | null;
	staerke_soll_unterfuehrer: number | null;
	staerke_soll_mannschaften: number | null;
	staerke_ist_fuehrer: number | null;
	staerke_ist_unterfuehrer: number | null;
	staerke_ist_mannschaften: number | null;
	propulsion?: string;
	tank_capacity_l?: number | null;
	fuel_consumption_l100km?: number | null;
	betriebsstoff_verbrauch?: number | null;
	betriebsstoff_tank?: number | null;
	betriebsstoff_fuellstand?: number | null;
	betriebsstoff_gemeldet_at?: string | null;
}
export interface TrackPosition {
	vehicle_id: string; lat: number; lon: number;
	speed_kmh: number | null; heading: number | null; recorded_at: string;
}
export interface TrackWaypointPublic {
	name: string; type: string;
	lat: number | null; lon: number | null;
	planned_arrival: string | null; planned_departure: string | null;
	halt_purpose: string | null;
}
export interface TrackPayload {
	name: string; organization: string | null; start_time: string | null;
	scope: ShareLinkScope;
	waypoints: TrackWaypointPublic[]; geojson: Geometry | null;
	distance_m: number | null;
	kanalwechsel?: KanalwechselEntry[];
	vehicles: TrackVehicle[]; positions: TrackPosition[];
}
export interface TrackGate {
	requires_password: true;
	convoy_name: string;
	/** Rolle des Links — steht schon vor der Passworteingabe bereit. */
	scope?: ShareLinkScope;
}

async function trackRequest<T>(path: string, init: RequestInit = {}, sessionToken?: string): Promise<T> {
	const baseUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
		...(init.headers as Record<string, string>),
	};
	if (sessionToken) headers['X-Track-Token'] = sessionToken;
	const res = await fetch(`${baseUrl}${path}`, { ...init, headers });
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: res.statusText }));
		throw new Error(err.detail ?? 'Request failed');
	}
	if (res.status === 204) return undefined as T;
	return res.json();
}

export const trackApi = {
	get: (slug: string, sessionToken?: string) =>
		trackRequest<TrackPayload | TrackGate>(`/api/track/${slug}`, {}, sessionToken),
	auth: (slug: string, password: string) =>
		trackRequest<{ token: string }>(`/api/track/${slug}/auth`, {
			method: 'POST',
			body: JSON.stringify({ password }),
		}),
};

export function isTrackGate(payload: TrackPayload | TrackGate): payload is TrackGate {
	return (payload as TrackGate).requires_password === true;
}

export interface AdminUser {
    id: string;
    email: string;
    first_name: string | null;
    last_name: string | null;
    is_active: boolean;
    is_superadmin: boolean;
    is_demo: boolean;
    mfa_enabled: boolean;
    created_at: string;
    orgs: { id: string; name: string; role: string }[];
}

export interface AdminUserCreate {
    email: string;
    /** Optional — when omitted the backend generates a strong random password. */
    password?: string;
    first_name?: string;
    last_name?: string;
    is_superadmin?: boolean;
    /** Optional org to assign the new user to on creation. */
    org_id?: string;
    org_role?: string;
}

export interface AdminUserUpdate {
    is_active?: boolean;
    is_superadmin?: boolean;
    email?: string;
    password?: string;
    first_name?: string;
    last_name?: string;
}

export interface AdminOrg {
    id: string;
    name: string;
    slug: string;
    owner_id: string | null;
    owner_email: string | null;
    member_count: number;
    is_demo: boolean;
}

export interface ApiKey {
    id: string;
    /** null for system-scoped keys — they belong to the instance, not a tenant. */
    organization_id: string | null;
    scope: 'organization' | 'system';
    name: string;
    prefix: string;
    role: string;
    created_at: string;
    last_used_at: string | null;
    expires_at: string | null;
    revoked: boolean;
}

export interface ApiKeyCreated extends ApiKey {
    /** Plaintext key — shown exactly once on creation. */
    key: string;
}

export interface ApiKeyCreate {
    name: string;
    role: string;
    expires_at?: string | null;
}

/** System keys carry no organization and no role — only a name and an expiry. */
export interface SystemApiKeyCreate {
    name: string;
    expires_at?: string | null;
}

export interface SmtpConfig {
    host: string;
    port: number;
    username: string;
    password: string;
    from_email: string;
    from_name: string;
    use_tls: 'starttls' | 'ssl' | 'false';
}

export interface SmtpConfigResponse {
    host: string;
    port: number;
    username: string;
    password_set: boolean;
    from_email: string;
    from_name: string;
    use_tls: string;
    configured: boolean;
}

export const adminApi = {
    listUsers: () => api.get<AdminUser[]>('/api/admin/users'),
    createUser: (data: AdminUserCreate) => api.post<AdminUser>('/api/admin/users', data),
    updateUser: (id: string, data: AdminUserUpdate) => api.patch<AdminUser>(`/api/admin/users/${id}`, data),
    deleteUser: (id: string) => api.delete(`/api/admin/users/${id}`),
    addUserToOrg: (userId: string, orgId: string, role: string) =>
        api.post(`/api/admin/users/${userId}/orgs`, { org_id: orgId, role }),
    removeUserFromOrg: (userId: string, orgId: string) =>
        api.delete(`/api/admin/users/${userId}/orgs/${orgId}`),
    listOrgs: () => api.get<AdminOrg[]>('/api/admin/organizations'),
    createOrg: (data: { name: string; slug: string }) => api.post<AdminOrg>('/api/admin/organizations', data),
    updateOrg: (id: string, data: { owner_id: string }) => api.patch<AdminOrg>(`/api/admin/organizations/${id}`, data),
    deleteOrg: (id: string) => api.delete(`/api/admin/organizations/${id}`),
    listApiKeys: (orgId: string) => api.get<ApiKey[]>(`/api/admin/organizations/${orgId}/api-keys`),
    createApiKey: (orgId: string, data: ApiKeyCreate) =>
        api.post<ApiKeyCreated>(`/api/admin/organizations/${orgId}/api-keys`, data),
    revokeApiKey: (orgId: string, keyId: string) =>
        api.delete(`/api/admin/organizations/${orgId}/api-keys/${keyId}`),
    listSystemApiKeys: () => api.get<ApiKey[]>('/api/admin/system-api-keys'),
    createSystemApiKey: (data: SystemApiKeyCreate) =>
        api.post<ApiKeyCreated>('/api/admin/system-api-keys', data),
    revokeSystemApiKey: (keyId: string) => api.delete(`/api/admin/system-api-keys/${keyId}`),
    getUpdateStatus: () => api.get<UpdateStatus>('/api/admin/update-status'),
    triggerUpdate: () => api.post<{ status: string }>('/api/admin/trigger-update', {}),
    getGithubTokenStatus: () => api.get<{ set: boolean; source: string | null }>('/api/admin/settings/github-token-set'),
    setGithubToken: (token: string) => api.put<void>('/api/admin/settings/github-token', { token }),
    getTrafficKeys: () => api.get<TrafficKeysResponse>('/api/admin/settings/traffic-keys'),
    setTrafficKeys: (data: { here_key?: string; tomtom_key?: string; provider?: string }) =>
        api.put<void>('/api/admin/settings/traffic-keys', data),
    getUpdateChannel: () => api.get<UpdateChannel>('/api/admin/settings/update-channel'),
    setUpdateChannel: (channel: UpdateChannelName) =>
        api.put<void>('/api/admin/settings/update-channel', { channel }),
    getUpdateMode: () => api.get<UpdateMode>('/api/admin/settings/update-mode'),
    setUpdateMode: (mode: 'auto' | 'notify', notify_on_auto?: boolean) =>
        api.put<void>('/api/admin/settings/update-mode',
            notify_on_auto === undefined ? { mode } : { mode, notify_on_auto }),
    getDemoSettings: () => api.get<DemoSettings>('/api/admin/settings/demo'),
    saveDemoSettings: (
        enabled: boolean,
        session_hours?: number,
        ip_cooldown_hours?: number,
        followup_enabled?: boolean,
    ) =>
        api.put<DemoSettings>('/api/admin/settings/demo', {
            enabled, session_hours, ip_cooldown_hours, followup_enabled,
        }),
    listDemoIpLocks: () => api.get<DemoIpLock[]>('/api/admin/demo-ip-locks'),
    releaseDemoIpLock: (ip: string) =>
        api.delete(`/api/admin/demo-ip-locks/${encodeURIComponent(ip)}`),
    listDemoIpAllowlist: () => api.get<DemoIpAllowlistEntry[]>('/api/admin/demo-ip-allowlist'),
    addDemoIpAllowlistEntry: (pattern: string, note?: string) =>
        api.post<DemoIpAllowlistEntry>('/api/admin/demo-ip-allowlist', { pattern, note }),
    removeDemoIpAllowlistEntry: (entryId: string) =>
        api.delete(`/api/admin/demo-ip-allowlist/${entryId}`),
    listDemoSessions: () => api.get<DemoSessionInfo[]>('/api/admin/demo-sessions'),
    getDemoStats: () => api.get<DemoStats>('/api/admin/demo-stats'),
    listDemoLeads: () => api.get<DemoLeadInfo[]>('/api/admin/demo-leads'),
    deleteDemoLead: (leadId: string) => api.delete(`/api/admin/demo-leads/${leadId}`),
    endDemoSession: (orgId: string) => api.delete(`/api/admin/demo-sessions/${orgId}`),
    extendDemoSession: (orgId: string, hours = 24) =>
        api.post<DemoSessionInfo>(`/api/admin/demo-sessions/${orgId}/extend`, { hours }),
    getSmtpSettings: () => api.get<SmtpConfigResponse>('/api/admin/settings/smtp'),
    saveSmtpSettings: (data: SmtpConfig) => api.put<void>('/api/admin/settings/smtp', data),
    testSmtp: () => api.post<{ status: string }>('/api/admin/settings/smtp/test', {}),
    sendUserPassword: (userId: string) => api.post<{ status: string; email: string }>(`/api/admin/users/${userId}/send-password`, {}),
    resetUserPassword: (userId: string) => api.post<{ password: string; email: string }>(`/api/admin/users/${userId}/reset-password`, {}),
    resetUserMfa: (userId: string) => api.post<{ status: string }>(`/api/admin/users/${userId}/reset-mfa`, {}),
    exportUserData: (userId: string) => api.get<Record<string, unknown>>(`/api/admin/users/${userId}/export`),
    eraseUserData: (userId: string) => api.delete(`/api/admin/users/${userId}/data`),
};

// stable = published releases; beta = numbered pre-releases (release
// candidates); nightly = every commit on main.
export type UpdateChannelName = 'stable' | 'beta' | 'nightly';

export interface UpdateStatus {
    deployed_sha: string | null;
    deployed_at: string | null;
    remote_sha: string | null;
    update_available: boolean;
    github_reachable: boolean;
    channel: UpdateChannelName;
    latest_release: string | null;   // (pre-)release tag the target resolves to (stable/beta); null on nightly
    no_release: boolean;             // channel has no (pre-)release/build target yet
    ahead_of_release: boolean;       // deployed build is newer than the target tag (e.g. was on nightly)
}

export interface UpdateChannel {
    channel: UpdateChannelName;
    source: 'db' | 'env';
    env_channel: UpdateChannelName;
}

export interface TrafficKeyState {
    set: boolean;
    source: 'db' | 'env' | null;
}
export interface TrafficKeysResponse {
    here: TrafficKeyState;
    tomtom: TrafficKeyState;
    provider: string | null;
    forced: string;
}
export interface UpdateMode {
    mode: 'auto' | 'notify';
    source: 'db' | 'env';
    env_mode: 'auto' | 'notify';
    notify_on_auto: boolean;   // E-Mail an Superadmins nach automatischer Installation
}

export interface DemoSettings {
    enabled: boolean;
    source: 'db' | 'env';
    env_enabled: boolean;
    session_hours: number;
    /** Karenzzeit je IP-Adresse in Stunden; 0 = keine Sperre. */
    ip_cooldown_hours: number;
    /** Nachfrage-Mail nach Ablauf einer Sitzung. */
    followup_enabled: boolean;
    /** Ohne SMTP bleibt der Schalter oben wirkungslos. */
    smtp_configured: boolean;
}

export interface DemoIpLock {
    ip: string;
    last_created_at: string;
    blocked_until: string;
    sessions: number;
}

/** Dauerhaft von der Karenzzeit ausgenommene Adresse oder Netz (CIDR). */
export interface DemoIpAllowlistEntry {
    id: string;
    pattern: string;
    note: string | null;
    created_at: string;
    created_by: string | null;
}

export interface DemoSessionInfo {
    id: string;
    name: string;
    slug: string;
    created_at: string;
    expires_at: string;
    convoy_count: number;
    created_ip: string | null;
    created_location: string | null;
    /** Beim Start angegebene Kontaktdaten; null bei Sitzungen von vor der Abfrage. */
    contact_email: string | null;
    contact_name: string | null;
}

/** Kennzahlen für die Übersicht im Demo-Tab (in SQL gezählt, nicht aus den Listen). */
export interface DemoStats {
    sessions_open: number;
    sessions_expiring_24h: number;
    convoys_in_demo: number;
    leads_total: number;
    leads_last_7d: number;
    leads_last_30d: number;
    followups_sent: number;
    /** Sitzung abgelaufen, Mail steht im nächsten Durchgang an. */
    followups_due: number;
    /** Sitzung läuft noch — die Nachfrage kommt später. */
    followups_waiting: number;
    /** Nach drei Fehlversuchen aufgegeben. */
    followups_failed: number;
    unsubscribed: number;
    ip_locks_active: number;
    allowlist_entries: number;
}

/** Ein Interessent aus dem Demo-Start — bleibt über die Sitzung hinaus stehen. */
export interface DemoLeadInfo {
    id: string;
    email: string;
    first_name: string | null;
    last_name: string | null;
    org_slug: string;
    created_at: string;
    session_expires_at: string;
    /** false = die Demo-Umgebung ist bereits gelöscht. */
    session_active: boolean;
    followup_sent_at: string | null;
    followup_attempts: number;
    followup_error: string | null;
    unsubscribed_at: string | null;
}

// ── Regionswechsel ────────────────────────────────────────────────────────────

/** Aktuell aktive Kartenregion, gelesen aus `.region` (siehe backend/app/api/routes/region.py). */
export interface RegionCurrent {
    url: string;
    filename: string;
    java_opts: string;
    /**
     * Die Bestandteile der Karte als Geofabrik-Pfade, z. B.
     * `["europe/dach", "europe/italy"]`. Immer gefüllt — bei einer einzelnen
     * Region mit genau einem Eintrag. Nötig, weil eine zusammengesetzte Region
     * auf der Platte `merged-<hash>.osm.pbf` heißt: Der Name identifiziert die
     * Zusammensetzung, nennt sie aber nicht.
     */
    sources: string[];
}

/**
 * Ein Eintrag aus dem Geofabrik-Index (555 Regionen). `path` ist die
 * menschenlesbare Eltern-Kette, z. B. "Europe › Germany › Bayern" —
 * `size_bytes` liefert der Endpunkt bewusst nicht mit (immer `null` im
 * Backend, siehe geofabrik.list_regions()); Extract-Größen kommen
 * ausschließlich aus `preview()`.
 */
export interface RegionEntry {
    id: string;
    name: string;
    path: string;
    url: string;
}

/** Ergebnis der nebenwirkungsfreien Vorab-Rechnung (`POST /region/preview`). */
export interface RegionPreview {
    /** Regionspfade der Bestandteile, sortiert (z. B. "europe/germany"). */
    sources: string[];
    /** true bei mehr als einem Bestandteil. */
    composed: boolean;
    /** Paare (Oberregion, Unterregion) — erlaubt, aber verschwenderisch. */
    overlapping: [string, string][];
    extract_bytes: number;
    graph_bytes: number;
    ram_needed_bytes: number;
    ram_available_bytes: number;
    /**
     * Heap des laufenden GraphHopper, der im Wartungsmodus frei wird — sonst 0.
     * Ohne pausiertes Routing läuft GraphHopper während des Imports weiter und
     * gibt nichts her; früher wurde der Betrag trotzdem immer gutgeschrieben,
     * und das Panel meldete "knapp", wo der Updater mangels Speicher scheiterte.
     */
    ram_reclaimable_bytes: number;
    ram_effective_available_bytes: number;
    disk_needed_bytes: number;
    disk_free_bytes: number;
    duration_minutes: [number, number];
    verdict: 'ok' | 'knapp' | 'reicht nicht';
    reason: string;
}

/** Phasen aus docker/updater/switch-region.sh — Namen müssen exakt stimmen. */
export type RegionPhase =
    // 'queued': Die Anforderung liegt im geteilten Volume, der Updater hat sie
    // noch nicht aufgegriffen. Kommt nicht aus der Statusdatei des Updaters,
    // sondern leitet das Backend aus der Anforderung selbst ab — ohne diese
    // Phase zeigte das Panel zwischen Klick und Aufgreifen entweder nichts
    // oder das Ergebnis des vorigen Wechsels.
    //
    // 'scheduled': Die Anforderung trägt einen Zeitpunkt und wartet darauf —
    // womöglich stundenlang. Als 'queued' gemeldet stünde im Panel dauerhaft
    // "wartet auf den Updater", was nach Störung aussieht statt nach Plan.
    //
    // 'cancelled': Der Wechsel wurde vom Bediener abbestellt. Eigene Phase,
    // weil der Updater das frueher als 'failed' meldete — das Panel zeigte
    // einen roten Fehlerbalken ueber einer Aktion, die genau so gewollt war.
    | 'idle' | 'queued' | 'scheduled' | 'checking' | 'downloading' | 'merging'
    | 'importing' | 'switching' | 'cleaning' | 'done' | 'failed' | 'cancelled';

export interface RegionStatus {
    phase: RegionPhase;
    message?: string;
    at?: string;
    /** Nur bei phase === 'scheduled': ISO-Zeitpunkt des geplanten Starts. */
    scheduled_for?: string;
    /** Nur bei phase === 'scheduled': ob das Routing dabei pausiert wird. */
    pause_routing?: boolean;
}

/** Optionen für Vorab-Rechnung und Wechsel. */
export interface RegionSwitchOptions {
    /**
     * Routing während des Imports anhalten. Macht den Heap des laufenden
     * GraphHopper für den Import frei — ohne das ist eine große kombinierte
     * Karte auf einer Maschine mit knappem Speicher nicht baubar. Preis: keine
     * Routenplanung, bis der Wechsel durch ist.
     */
    pauseRouting?: boolean;
    /** ISO-Zeitpunkt, zu dem der Updater starten soll. Ohne Angabe: sofort. */
    scheduledFor?: string;
}

export const regionApi = {
    current: () => api.get<RegionCurrent>('/api/admin/region'),
    list: () => api.get<RegionEntry[]>('/api/admin/regions'),
    preview: (urls: string[], opts: RegionSwitchOptions = {}) =>
        api.post<RegionPreview>('/api/admin/region/preview', {
            urls,
            pause_routing: opts.pauseRouting ?? false,
        }),
    switch: (urls: string[], opts: RegionSwitchOptions = {}) =>
        api.post<{ status: string }>('/api/admin/region', {
            urls,
            pause_routing: opts.pauseRouting ?? false,
            // Nur mitschicken, wenn wirklich ein Termin gewählt wurde: `null`
            // bedeutet serverseitig dasselbe wie "fehlt", aber ein leerer
            // String käme als Validierungsfehler zurück.
            ...(opts.scheduledFor ? { scheduled_for: opts.scheduledFor } : {}),
        }),
    status: () => api.get<RegionStatus>('/api/admin/region/status'),
    cancel: () => api.post<{ status: string }>('/api/admin/region/cancel', {}),
    /**
     * SSE-Strom der Live-Ausgabe des Updaters (`region.log`) — inklusive der
     * Ausgabe des Import-Containers. Ohne ihn zeigte das Terminal nur die
     * fünf bis acht Phasenmeldungen aus `status()`, bei einem zweistündigen
     * Import also eine einzige Zeile.
     *
     * Kurzlebiges Stream-Ticket als Query-Parameter, weil EventSource keinen
     * Authorization-Header setzen kann (wie `usersApi.onlineStream` und das
     * Update-Log). `null`, wenn kein Ticket zu bekommen ist — der Aufrufer
     * entscheidet, was er dem Bediener dann anzeigt.
     */
    logStream: async (): Promise<EventSource | null> => {
        const ticket = await getStreamTicket();
        if (!ticket) return null;
        return new EventSource(`/api/admin/region/log?token=${encodeURIComponent(ticket)}`);
    },
};

// ── Systemübersicht ───────────────────────────────────────────────────────────

export interface DiskUsage {
    path: string;
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
    percent: number;
}

export interface ContainerInfo {
    name: string;
    image: string;
    /** running | exited | restarting | created | paused | dead */
    state: string;
    status: string;
    health: 'healthy' | 'unhealthy' | 'starting' | null;
    created_at: number | null;
    restart_count: number | null;
    cpu_percent: number | null;
    mem_bytes: number | null;
    mem_limit_bytes: number | null;
    mem_percent: number | null;
}

export interface DockerReport {
    available: boolean;
    reason: string | null;
    engine_version: string | null;
    total: number;
    running: number;
    unhealthy: number;
    containers: ContainerInfo[];
}

export interface HostMetrics {
    cpu_percent: number | null;
    cpu_count: number | null;
    load1: number | null;
    load5: number | null;
    load15: number | null;
    uptime_seconds: number | null;
    mem_total_bytes: number | null;
    mem_used_bytes: number | null;
    mem_available_bytes: number | null;
    mem_percent: number | null;
    swap_total_bytes: number | null;
    swap_used_bytes: number | null;
    disk_total_bytes: number | null;
    disk_used_bytes: number | null;
    disk_percent: number | null;
    disk_read_bytes_s: number | null;
    disk_write_bytes_s: number | null;
    disk_util_percent: number | null;
    /** PSI „some avg10" — Anteil der Zeit mit Wartezeit auf die Ressource. */
    psi_cpu_avg10: number | null;
    psi_mem_avg10: number | null;
    psi_io_avg10: number | null;
    psi_io_avg60: number | null;
    disks: DiskUsage[];
}

export interface SystemOverview {
    checked_at: string;
    collector: {
        enabled: boolean;
        interval_s: number;
        last_sample_at: string | null;
        raw_retention_days: number;
        daily_retention_days: number;
    };
    host: HostMetrics;
    docker: DockerReport;
    database: {
        size_bytes: number | null;
        connections: number | null;
        users: number | null;
        organizations: number | null;
        convoys: number | null;
    };
    /** Portalnutzung. `active_users`/`unique_users_today` zählen ausschließlich
     *  reguläre Portalnutzer — Demo-Besucher und Superadmins stehen daneben. */
    usage: {
        active_users: number;
        active_demo_users: number;
        active_admin_users: number;
        active_orgs: number;
        window_seconds: number;
        requests_since_flush: number;
        errors_since_flush: number;
        avg_response_ms: number | null;
        unique_users_today: number;
        unique_demo_users_today: number;
        unique_admin_users_today: number;
        logins_24h: number;
    };
}

/** Ein Punkt der Zeitreihe. Feldnamen entsprechen den Metrik-Spalten; je nach
 *  Auflösung kommen aggregierte Zusatzfelder (…_max) dazu. */
export interface MetricPoint {
    t: string;
    [key: string]: number | string | null;
}

export interface MetricSeries {
    resolution: 'raw' | 'hour' | 'day';
    from: string;
    to: string;
    points: MetricPoint[];
}

/** Nutzung eines Tages, nach Gruppen getrennt: `users` sind reguläre
 *  Portalnutzer, `demo_users` Probesitzungen, `admin_users` Superadmins im
 *  Admin-Portal. */
export interface UsageDay {
    day: string;
    users: number;
    demo_users: number;
    admin_users: number;
    orgs: number;
    requests: number;
    demo_requests: number;
    admin_requests: number;
}

export interface UsageHistory {
    from: string;
    to: string;
    unique_users: number;
    unique_demo_users: number;
    unique_admin_users: number;
    days: UsageDay[];
}

export interface MonthlyReport {
    month: string;
    from: string;
    to: string;
    generated_at: string;
    days_covered: number;
    summary: Record<string, number | string | null>;
    days: MetricPoint[];
    usage_by_day: UsageDay[];
}

export type MetricRange = '1h' | '6h' | '24h' | '7d' | '30d' | '90d' | '365d';

export const systemApi = {
    overview: () => api.get<SystemOverview>('/api/admin/system/overview'),
    containers: (withStats = true) =>
        api.get<DockerReport>(`/api/admin/system/containers?with_stats=${withStats}`),
    history: (range: MetricRange, resolution: 'auto' | 'raw' | 'hour' | 'day' = 'auto') =>
        api.get<MetricSeries>(`/api/admin/system/history?range=${range}&resolution=${resolution}`),
    usage: (days = 30) => api.get<UsageHistory>(`/api/admin/system/usage?days=${days}`),
    reportMonths: () =>
        api.get<{ months: string[]; current: string }>('/api/admin/system/reports/months'),
    monthlyReport: (month: string) =>
        api.get<MonthlyReport>(`/api/admin/system/reports/monthly?month=${month}`),
    sampleNow: () =>
        api.post<{ status: string; captured_at: string }>('/api/admin/system/sample', {}),
    /** Monatsbericht als Datei herunterladen (der Endpunkt braucht den Token,
     *  ein einfacher Link würde ihn nicht mitschicken). */
    downloadReport: (month: string, format: 'csv' | 'pdf') =>
        downloadFile(
            `/api/admin/system/reports/monthly?month=${month}&format=${format}`,
            `convoyplan-systembericht-${month}.${format}`,
        ),
    downloadHistoryCsv: (range: MetricRange, resolution: 'auto' | 'raw' | 'hour' | 'day' = 'auto') =>
        downloadFile(
            `/api/admin/system/history?range=${range}&resolution=${resolution}&format=csv`,
            `convoyplan-verlauf-${range}.csv`,
        ),
};

export interface BrandingData {
    app_name: string;
    logo_main_url: string | null;
    logo_horizontal_url: string | null;
    color_primary: string;
    color_primary_hover: string;
    color_accent: string;
    color_bg: string;
    color_surface: string;
    color_nav_bg: string;
    color_nav_text: string;
    color_text: string;
    color_text_muted: string;
}

export interface BrandingUpdate {
    app_name: string;
    color_primary: string;
    color_primary_hover: string;
    color_accent: string;
    color_bg: string;
    color_surface: string;
    color_nav_bg: string;
    color_nav_text: string;
    color_text: string;
    color_text_muted: string;
}

export const brandingApi = {
    get: () => api.get<BrandingData>('/api/branding'),
    update: (data: BrandingUpdate) => api.put<BrandingData>('/api/branding', data),
    uploadLogo: (slot: 'main' | 'horizontal', file: File) =>
        uploadFile<BrandingData>(`/api/branding/logo/${slot}`, file),
};

// Org-scoped Branding: wirkt nur für die eigene Organisation (Org-Admin),
// nie plattformweit. reset() entfernt alle Overrides → Plattform-Branding.
export const orgBrandingApi = {
    get: () => api.get<BrandingData>('/api/org/branding'),
    update: (data: BrandingUpdate) => api.put<BrandingData>('/api/org/branding', data),
    uploadLogo: (slot: 'main' | 'horizontal', file: File) =>
        uploadFile<BrandingData>(`/api/org/branding/logo/${slot}`, file),
    reset: () => api.delete<BrandingData>('/api/org/branding'),
};

export interface ZusatzKanal {
    name: string;
    kanal: string;
}

export type LeitstelleStatus = 'global' | 'local' | 'pending' | 'rejected';

export interface Leitstelle {
    id: string;
    name: string;
    anrufgruppe: string;
    zusatz_kanaele: ZusatzKanal[];
    has_geometry: boolean;
    district_codes: string[];
    org_id: string | null;
    org_name: string | null;
    status: LeitstelleStatus;
    proposed_by_org_id: string | null;
    proposed_by_org_name: string | null;
    review_note: string | null;
}

export interface LeistelleDetail extends Leitstelle {
    geometry_geojson: object | null;
}

export interface LeitstellePayload {
    name: string;
    anrufgruppe: string;
    zusatz_kanaele: ZusatzKanal[];
    district_codes?: string[] | null;
}

export interface LicenseStatus {
    valid: boolean;
    demo_mode: boolean;
    license_id: string | null;
    customer: string | null;
    email: string | null;
    issued: string | null;
    expires: string | null;
    max_users: number | null;
    instance_id: string;
    key_source: string | null;
    error: string | null;
}

export interface McpScopeInfo {
    scope: string;
    label: string;
}

export interface McpOrgChoice {
    id: string;
    name: string;
    slug: string;
    role: string;
    /**
     * Ob die Organisation den Zugriff über die KI-Schnittstelle überhaupt
     * freigegeben hat. Standard ist nein — dann hilft auch die Rolle nicht,
     * und die Organisation steht nur als Erklärung in der Liste.
     */
    mcp_enabled: boolean;
    /**
     * Welche Ausschnitte der Fachdaten diese Organisation freigibt. Nicht
     * wählbar, sondern eine Einstellung der Organisation — steht dort, weil
     * es die Verbindung genauso begrenzt wie die Berechtigungen.
     */
    bereiche: { bereich: string; label: string }[];
    /** Welche der angefragten Berechtigungen diese Organisation hergibt. */
    grantable_scopes: string[];
    /**
     * Was die Rolle darüber hinaus hergäbe, das Programm aber nicht
     * angefragt hat. Anzukreuzen, nicht vorausgewählt — manche Clients
     * (ChatGPT etwa) fragen einmalig beim Verbinden und können später nicht
     * nachfordern.
     */
    optional_scopes: string[];
}

export interface McpConsentRequest {
    client_id: string;
    /** Selbstauskunft aus der Registrierung — siehe client_name_verified. */
    client_name: string;
    /**
     * Immer false. Der Name stammt aus der Client-Registrierung, und
     * registrieren darf sich jeder. Die Oberfläche muss ihn entsprechend
     * kennzeichnen; verlässlich ist nur redirect_host.
     */
    client_name_verified: boolean;
    /** Der überprüfte Host der registrierten Redirect-URI. */
    redirect_host: string;
    requested_scopes: McpScopeInfo[];
    /** Beschriftungen der Berechtigungen, die das Programm nicht angefragt hat. */
    optional_scopes: McpScopeInfo[];
    organizations: McpOrgChoice[];
    /** Wann die Anfrage verfällt (ISO-8601). */
    expires_at: string;
}

export const mcpApi = {
    readConsentRequest: (request: string) =>
        api.get<McpConsentRequest>(`/api/mcp/consent?request=${encodeURIComponent(request)}`),
    decide: (
        request: string,
        approve: boolean,
        organization_id: string | null,
        scopes: string[] | null = null
    ) =>
        api.post<{ redirect_url: string }>('/api/mcp/consent', {
            request,
            approve,
            organization_id,
            scopes,
        }),
};

/** Ein anzukreuzendes Kästchen samt Beschriftung, vom Server geliefert. */
export interface McpWahlmoeglichkeit {
    wert: string;
    label: string;
}

export interface OrgMcpPolicy {
    enabled: boolean;
    scopes: string[];
    bereiche: string[];
    /** Ob je etwas eingestellt wurde — trennt „abgeschaltet" von „nie angefasst". */
    konfiguriert: boolean;
    /** Der Schalter des Betreibers. Ohne ihn nützt die eigene Freigabe nichts. */
    instanz_aktiv: boolean;
    verbindungs_url: string;
    verfuegbare_scopes: McpWahlmoeglichkeit[];
    verfuegbare_bereiche: McpWahlmoeglichkeit[];
    /** Steht nicht zur Wahl: ohne ihn käme keine Verbindung zustande. */
    basis_scope: string;
    aktive_verbindungen: number;
    updated_at: string | null;
}

export interface OrgMcpConnection {
    family_id: string;
    client_id: string;
    /** Selbstauskunft aus der Registrierung, ungeprüft. */
    client_name: string;
    user_id: string;
    user_email: string | null;
    scopes: string[];
    created_at: string;
    last_used_at: string | null;
    expires_at: string;
}

export const orgMcpApi = {
    read: () => api.get<OrgMcpPolicy>('/api/org/mcp'),
    save: (policy: { enabled: boolean; scopes: string[]; bereiche: string[] }) =>
        api.put<OrgMcpPolicy>('/api/org/mcp', policy),
    listConnections: () => api.get<OrgMcpConnection[]>('/api/org/mcp/connections'),
    disconnect: (familyId: string) =>
        api.delete<void>(`/api/org/mcp/connections/${familyId}`),
};

export interface McpStatus {
    /** Der geltende Zustand: Einstellung aus der Datenbank schlägt Umgebung. */
    enabled: boolean;
    /** Woher er kommt — "db" (im Portal gesetzt) oder "env" (aus der .env). */
    source: 'db' | 'env';
    /** Was in MCP_ENABLED steht. Zeigt an, worauf ein Zurücksetzen fiele. */
    env_enabled: boolean;
    allow_dcr: boolean;
    /** Ob sich Programme per Metadatendokument ausweisen dürfen (CIMD). */
    allow_cimd: boolean;
    /** Woher dieser Zustand kommt — "db" (im Portal gesetzt) oder "env". */
    cimd_source: 'db' | 'env';
    /** Was in MCP_ALLOW_CIMD steht. Zeigt an, worauf ein Zurücksetzen fiele. */
    env_allow_cimd: boolean;
    /** Die Adresse, die ein Client als Remote-MCP-Server einträgt. */
    connection_url: string;
    issuer_url: string;
    access_token_ttl_minutes: number;
    refresh_token_ttl_days: number;
    tool_calls_per_minute: number;
    registered_clients: number;
    active_connections: number;
    /**
     * Wie viele Organisationen die Schnittstelle nutzen — und wie viele es
     * überhaupt gibt. Der Instanzschalter sagt darüber nichts: eingeschaltet
     * heißt nur, dass es `/mcp` gibt, nicht dass jemand teilnimmt.
     */
    organizations_enabled: number;
    organizations_total: number;
    /**
     * Ob der Reverse Proxy die MCP-Pfade ans Backend leitet.
     *
     * `null` heißt „nicht feststellbar" (Caddys Admin-API antwortet nicht) und
     * ist nicht dasselbe wie `false`. Ohne diese Angabe zeigte das Portal „An"
     * samt Verbindungsadresse, während von außen nichts erreichbar war — der
     * Schalter mountet nur die Routen im Backend.
     */
    proxy_routes_live: boolean | null;
    /** Ob sich das aus dem Portal heraus reparieren lässt. */
    proxy_repairable: boolean;
    /** Klartext für den Betreiber, oder null wenn alles passt. */
    proxy_hint: string | null;
    /** Was der Reparatur-Knopf erreicht hat — nur dessen Antwort trägt es. */
    proxy_repair_note?: string | null;
}

export interface McpClient {
    client_id: string;
    client_name: string;
    /** Immer false — siehe McpConsentRequest.client_name_verified. */
    name_verified: boolean;
    redirect_uris: string[];
    created_at: string;
    last_used_at: string | null;
    revoked: boolean;
    active_connections: number;
    /**
     * Ob „Verwaiste entfernen" diese Zeile mitnähme — keine Tokens, keine
     * Codes, alt genug. Das Portal zeigt damit vorher an, was der Knopf tut.
     */
    orphaned: boolean;
}

export interface McpConnection {
    family_id: string;
    client_id: string;
    client_name: string;
    user_id: string;
    user_email: string | null;
    organization_id: string;
    organization_name: string | null;
    scopes: string[];
    created_at: string;
    last_used_at: string | null;
    expires_at: string;
}

/** Was eine Organisation über die KI-Schnittstelle hergibt — nur zum Ansehen. */
export interface McpOrgPolicy {
    organization_id: string;
    name: string;
    slug: string;
    is_demo: boolean;
    enabled: boolean;
    scopes: string[];
    bereiche: string[];
    /** Ob je etwas eingestellt wurde — trennt „abgeschaltet" von „nie angefasst". */
    konfiguriert: boolean;
    active_connections: number;
    updated_at: string | null;
}

export const mcpAdminApi = {
    status: () => api.get<McpStatus>('/api/admin/mcp/status'),
    /**
     * Alle Organisationen mit ihrem KI-Zugriff — auch die abgeschalteten.
     *
     * Rein lesend: einstellen kann es nur der Admin der Organisation. Wer die
     * Instanz betreibt, sieht *dass* eine Organisation teilnimmt und in
     * welchem Umfang, entscheidet aber nicht über ihre Einsatzdaten.
     */
    listOrganizations: () => api.get<McpOrgPolicy[]>('/api/admin/mcp/organizations'),
    /** Die Schnittstelle ein- oder ausschalten. Wirkt sofort, ohne Neustart. */
    setEnabled: (enabled: boolean) =>
        api.put<McpStatus>('/api/admin/settings/mcp', { enabled }),
    /**
     * Ausweis per Metadatendokument (CIMD) erlauben oder verbieten.
     *
     * Wirkt sofort. Eingeschaltet ruft die Instanz beim Verbinden eine
     * Adresse ab, die der Anfragende bestimmt — abgesichert in
     * `safe_fetch.py`, aber eine Fläche, die es ohne den Schalter nicht gibt.
     */
    setAllowCimd: (enabled: boolean) =>
        api.put<McpStatus>('/api/admin/settings/mcp/cimd', { enabled }),
    /**
     * Die MCP-Pfade im Reverse Proxy herstellen — ohne Zugriff auf den Server.
     *
     * Schreibt eine frische Proxy-Konfiguration und lädt sie sofort nach.
     * Wirft mit der Begründung im `detail`, wenn es nicht geht.
     */
    repairProxy: () => api.post<McpStatus>('/api/admin/mcp/proxy-repair', {}),
    listClients: () => api.get<McpClient[]>('/api/admin/mcp/clients'),
    /**
     * Verwaiste Registrierungen entfernen (`orphaned`).
     *
     * Entzieht keinen Zugang: eine Registrierung ist keiner. Was noch ein
     * Token oder einen Code trägt, bleibt stehen, ebenso alles aus der
     * letzten Stunde — ein laufender Verbindungsversuch soll den Knopf
     * überleben.
     */
    cleanupClients: () =>
        api.post<{ removed: number }>('/api/admin/mcp/clients/cleanup', {}),
    revokeClient: (clientId: string) =>
        api.delete(`/api/admin/mcp/clients/${encodeURIComponent(clientId)}`),
    listConnections: () => api.get<McpConnection[]>('/api/admin/mcp/connections'),
    disconnect: (familyId: string) =>
        api.delete(`/api/admin/mcp/connections/${encodeURIComponent(familyId)}`),
};

export const licenseApi = {
    getStatus: () => api.get<LicenseStatus>('/api/license/status'),
    activate: (license_key: string) =>
        api.post<LicenseStatus>('/api/license/activate', { license_key }),
    remove: () => api.delete<{ demo_mode: boolean }>('/api/license/'),
};

/** Kennung einer verwaltbaren Vorlage (siehe backend/app/api/routes/email_template.py). */
export type EmailTemplateKind = 'password' | 'demo_followup';

export interface EmailTemplate {
    kind: EmailTemplateKind;
    label: string;
    description: string;
    subject: string;
    html: string;
    is_custom: boolean;
    /** Platzhalter, die in dieser Vorlage etwas bedeuten. */
    placeholders: string[];
}

export interface EmailTemplateSummary {
    kind: EmailTemplateKind;
    label: string;
    description: string;
    is_custom: boolean;
}

export interface EmailTemplateUpdate {
    subject: string;
    html: string;
}

export const emailTemplateApi = {
    list: () => api.get<EmailTemplateSummary[]>('/api/admin/email-templates'),
    get: (kind: EmailTemplateKind) =>
        api.get<EmailTemplate>(`/api/admin/email-templates/${kind}`),
    update: (kind: EmailTemplateKind, data: EmailTemplateUpdate) =>
        api.put<EmailTemplate>(`/api/admin/email-templates/${kind}`, data),
    reset: (kind: EmailTemplateKind) =>
        api.post<EmailTemplate>(`/api/admin/email-templates/${kind}/reset`, {}),
    /** Musterexemplar an die eigene Adresse; liefert den tatsächlichen Empfänger zurück. */
    sendTest: (kind: EmailTemplateKind) =>
        api.post<{ status: string; recipient: string }>(
            `/api/admin/email-templates/${kind}/test`, {},
        ),
    previewUrl: (kind: EmailTemplateKind) => `/api/admin/email-templates/${kind}/preview`,
};

export const leistellenApi = {
    list: () => api.get<Leitstelle[]>('/api/leitstellen/'),
    get: (id: string) => api.get<LeistelleDetail>(`/api/leitstellen/${id}`),
    geojson: () => api.get<GeoJSON.FeatureCollection>('/api/leitstellen/geojson'),
    create: (data: LeitstellePayload) =>
        api.post<Leitstelle>('/api/leitstellen/', data),
    update: (id: string, data: Partial<LeitstellePayload>) =>
        api.put<Leitstelle>(`/api/leitstellen/${id}`, data),
    delete: (id: string) => api.delete(`/api/leitstellen/${id}`),
    approve: (id: string) => api.post<Leitstelle>(`/api/leitstellen/${id}/approve`, {}),
    reject: (id: string, note?: string) => api.post<Leitstelle>(`/api/leitstellen/${id}/reject`, { note: note ?? null }),
    importBoundary: (id: string, file: File) =>
        uploadFile<Leitstelle>(`/api/leitstellen/${id}/boundary`, file),
};

export const orgLeistellenApi = {
    list: () => api.get<Leitstelle[]>('/api/org/leitstellen/'),
    get: (id: string) => api.get<LeistelleDetail>(`/api/org/leitstellen/${id}`),
    geojson: () => api.get<GeoJSON.FeatureCollection>('/api/org/leitstellen/geojson'),
    create: (data: LeitstellePayload) =>
        api.post<Leitstelle>('/api/org/leitstellen/', data),
    update: (id: string, data: Partial<LeitstellePayload>) =>
        api.put<Leitstelle>(`/api/org/leitstellen/${id}`, data),
    delete: (id: string) => api.delete(`/api/org/leitstellen/${id}`),
    submit: (id: string) => api.post<Leitstelle>(`/api/org/leitstellen/${id}/submit`, {}),
    importBoundary: (id: string, file: File) =>
        uploadFile<Leitstelle>(`/api/org/leitstellen/${id}/boundary`, file),
};

export interface OrgLookupResult {
    name: string;
    slug: string;
}

export const orgAuthApi = {
    lookup: (slug: string) => api.get<OrgLookupResult>(`/api/auth/org-lookup?slug=${encodeURIComponent(slug)}`),
    loginOrg: (email: string, password: string, org_slug: string) =>
        api.post<LoginResult>('/api/auth/login', { email, password, org_slug }),
    mfaVerify: (mfa_token: string, code: string) =>
        api.post<LoginResult>('/api/auth/mfa/verify', { mfa_token, code }),
    requestPasswordReset: (email: string, org_slug: string) =>
        api.post<{ status: string }>('/api/auth/password-reset', { email, org_slug }),
};

// ── Meldungen: Fehler und Wünsche ────────────────────────────────────────────

export type FeedbackKind = 'bug' | 'feature';
export type FeedbackSeverity = 'niedrig' | 'normal' | 'hoch' | 'kritisch';
export type FeedbackStatus =
	| 'neu'
	| 'gesichtet'
	| 'geplant'
	| 'in_arbeit'
	| 'erledigt'
	| 'abgelehnt'
	| 'duplikat';

export interface FeedbackPayload {
	kind: FeedbackKind;
	title: string;
	description: string;
	severity: FeedbackSeverity;
	page_url?: string | null;
	user_agent?: string | null;
	app_version?: string | null;
	viewport?: string | null;
	/** Data-URL (PNG, JPEG oder WebP) — siehe `FeedbackModal.svelte`. */
	screenshot?: string | null;
}

export interface FeedbackSubmitted {
	id: string;
	kind: FeedbackKind;
	created_at: string;
}

export interface FeedbackReport {
	id: string;
	kind: FeedbackKind;
	title: string;
	description: string;
	severity: FeedbackSeverity;
	priority: FeedbackSeverity;
	status: FeedbackStatus;
	org_id: string | null;
	org_slug: string | null;
	org_name: string | null;
	org_vorhanden: boolean;
	user_id: string | null;
	reporter_email: string | null;
	reporter_name: string | null;
	reporter_role: string | null;
	is_demo: boolean;
	page_url: string | null;
	user_agent: string | null;
	app_version: string | null;
	viewport: string | null;
	has_screenshot: boolean;
	screenshot_bytes: number | null;
	admin_note: string | null;
	handled_by_email: string | null;
	handled_at: string | null;
	created_at: string;
	updated_at: string;
}

export interface FeedbackStats {
	gesamt: number;
	offen: number;
	bugs_offen: number;
	features_offen: number;
	kritisch_offen: number;
	neu_7_tage: number;
	je_status: Record<string, number>;
}

export const feedbackApi = {
	submit: (data: FeedbackPayload) => api.post<FeedbackSubmitted>('/api/feedback', data),
};

export interface FeedbackFilter {
	kind?: FeedbackKind | '';
	status?: FeedbackStatus | '';
	offen?: boolean;
}

export const feedbackAdminApi = {
	list: (filter: FeedbackFilter = {}) => {
		const q = new URLSearchParams();
		if (filter.kind) q.set('kind', filter.kind);
		if (filter.status) q.set('status', filter.status);
		if (filter.offen) q.set('offen', 'true');
		const qs = q.toString();
		// Ausdrücklich die organisationslose Sitzung: das Adminportal liegt
		// außerhalb jeder Organisation, und ein mitgeschickter `X-Org-Slug`
		// zeigte dort auf ein Cookie, das es nicht gibt.
		return api.get<FeedbackReport[]>(`/api/admin/feedback${qs ? `?${qs}` : ''}`, null);
	},
	stats: () => api.get<FeedbackStats>('/api/admin/feedback/stats', null),
	update: (
		id: string,
		data: { status?: FeedbackStatus; priority?: FeedbackSeverity; admin_note?: string }
	) => api.patch<FeedbackReport>(`/api/admin/feedback/${id}`, data, null),
	remove: (id: string) => api.delete(`/api/admin/feedback/${id}`, null),
	/** Die Adresse des Bildschirmfotos — hinter der Superadmin-Sitzung. */
	screenshotUrl: (id: string) => `/api/admin/feedback/${id}/screenshot`,
};
