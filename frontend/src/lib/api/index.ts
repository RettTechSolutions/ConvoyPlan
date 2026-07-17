import { api, uploadFile, getStreamTicket } from './client';
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
	order_index: number; range_km: number | null; range_uses_defaults: boolean;
}

export interface FuelStopPosition { lat: number; lon: number; }
export interface VehicleRangeInfo { name: string; callsign: string | null; range_km: number; using_defaults: boolean; propulsion?: Propulsion; }
export interface DurationHalt {
	stop_km: number;
	stop_position: FuelStopPosition | null;
	duration_min: number;
	is_rest: boolean;
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
}

export interface ConvoyVehicleItem {
	vehicle: Vehicle; position: number; vehicle_status: string;
	status_level: string | null; status_note: string | null; status_changed_at: string | null;
	sonderfunktion: string | null; mobile_phone: string | null;
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

export interface LoginResult {
	access_token: string | null;
	token_type: string;
	mfa_required: boolean;
	mfa_token: string | null;
}

// Auth
export interface DemoSessionResult {
    access_token: string;
    token_type: string;
    org_slug: string;
    expires_at: string;
}

export const authApi = {
	register: (email: string, password: string) => api.post('/api/auth/register', { email, password }),
	login: (email: string, password: string) =>
		api.post<LoginResult>('/api/auth/login', { email, password }),
	mfaVerify: (mfa_token: string, code: string) =>
		api.post<LoginResult>('/api/auth/mfa/verify', { mfa_token, code }),
	changePassword: (current_password: string, new_password: string) =>
		api.post<{ status: string; access_token?: string }>('/api/auth/password', { current_password, new_password }),
	requestPasswordReset: (email: string, org_slug?: string) =>
		api.post<{ status: string }>('/api/auth/password-reset', { email, org_slug }),
	createDemoSession: () => api.post<DemoSessionResult>('/api/auth/demo-session', {}),
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
export interface TrackGate { requires_password: true; convoy_name: string; }

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
    organization_id: string;
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
    saveDemoSettings: (enabled: boolean, session_hours?: number) =>
        api.put<DemoSettings>('/api/admin/settings/demo', { enabled, session_hours }),
    listDemoSessions: () => api.get<DemoSessionInfo[]>('/api/admin/demo-sessions'),
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
}

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

export const licenseApi = {
    getStatus: () => api.get<LicenseStatus>('/api/license/status'),
    activate: (license_key: string) =>
        api.post<LicenseStatus>('/api/license/activate', { license_key }),
    remove: () => api.delete<{ demo_mode: boolean }>('/api/license/'),
};

export interface EmailTemplate {
    subject: string;
    html: string;
    is_custom: boolean;
}

export interface EmailTemplateUpdate {
    subject: string;
    html: string;
}

export const emailTemplateApi = {
    get: () => api.get<EmailTemplate>('/api/admin/email-template'),
    update: (data: EmailTemplateUpdate) => api.put<EmailTemplate>('/api/admin/email-template', data),
    reset: () => api.post<EmailTemplate>('/api/admin/email-template/reset', {}),
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
