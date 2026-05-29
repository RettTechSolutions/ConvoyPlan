import { api, uploadFile } from './client';
import type { Geometry } from 'geojson';

export interface Point { lat: number; lon: number }

export type RoadPreference = 'schnell' | 'bundesstrasse' | 'landstrasse';

export interface Vehicle {
	id: string; name: string; callsign: string | null; license_plate: string | null;
	height_cm: number | null; weight_kg: number | null; length_cm: number | null; convoy_role: string | null;
	tank_capacity_l: number | null; fuel_consumption_l100km: number | null;
	current_fuel_l: number | null; order_index: number; range_km: number | null; range_uses_defaults: boolean;
}

export interface FuelStopPosition { lat: number; lon: number; }
export interface VehicleRangeInfo { name: string; callsign: string | null; range_km: number; using_defaults: boolean; }
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
}

export interface RouteResult {
	id: string; convoy_id: string; distance_m: number | null; duration_s: number | null;
	routing_params: Record<string, unknown> | null; geojson: Geometry | null;
	fuel_analysis: FuelAnalysis | null;
	kanalwechsel?: KanalwechselEntry[];
}

export interface Organization {
	id: string; name: string; description: string | null;
	member_count: number; my_role: string;
}

export interface OrgMember {
	user_id: string; email: string; role: string;
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
}

export interface LoginResult {
	access_token: string | null;
	token_type: string;
	mfa_required: boolean;
	mfa_token: string | null;
}

// Auth
export const authApi = {
	register: (email: string, password: string) => api.post('/api/auth/register', { email, password }),
	login: (email: string, password: string) =>
		api.post<LoginResult>('/api/auth/login', { email, password }),
	mfaVerify: (mfa_token: string, code: string) =>
		api.post<LoginResult>('/api/auth/mfa/verify', { mfa_token, code }),
	changePassword: (current_password: string, new_password: string) =>
		api.post<{ status: string }>('/api/auth/password', { current_password, new_password }),
	requestPasswordReset: (email: string, org_slug?: string) =>
		api.post<{ status: string }>('/api/auth/password-reset', { email, org_slug }),
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
	updateVehicleStatus: (convoyId: string, vehicleId: string, vehicle_status: string) =>
		api.patch(`/api/convoys/${convoyId}/vehicles/${vehicleId}/status`, { vehicle_status }),
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
	inviteMember: (orgId: string, email: string, password: string) =>
		api.post(`/api/organizations/${orgId}/members/invite`, { email, password }),
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
export const usersApi = {
	onlineStream: (): EventSource => new EventSource(`/api/users/online`),
};

// V3: Sperrungen
export const overpassApi = {
	getClosures: (lat: number, lon: number, radiusM = 15000) =>
		api.get<Record<string, unknown>>(`/api/overpass/closures?lat=${lat}&lon=${lon}&radius_m=${radiusM}`),
};

// Public share
export const shareApi = {
	get: (token: string) => api.get<{
		name: string; organization: string | null; start_time: string | null;
		waypoints: Waypoint[]; geojson: Geometry | null;
	}>(`/api/convoys/share/${token}`),
};

export interface AdminUser {
    id: string;
    email: string;
    is_active: boolean;
    is_superadmin: boolean;
    mfa_enabled: boolean;
    created_at: string;
    orgs: { id: string; name: string; role: string }[];
}

export interface AdminUserCreate {
    email: string;
    password: string;
    is_superadmin?: boolean;
}

export interface AdminUserUpdate {
    is_active?: boolean;
    is_superadmin?: boolean;
    email?: string;
    password?: string;
}

export interface AdminOrg {
    id: string;
    name: string;
    slug: string;
    owner_email: string | null;
    member_count: number;
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
    deleteOrg: (id: string) => api.delete(`/api/admin/organizations/${id}`),
    getUpdateStatus: () => api.get<UpdateStatus>('/api/admin/update-status'),
    triggerUpdate: () => api.post<{ status: string }>('/api/admin/trigger-update', {}),
    getGithubTokenStatus: () => api.get<{ set: boolean; source: string | null }>('/api/admin/settings/github-token-set'),
    setGithubToken: (token: string) => api.put<void>('/api/admin/settings/github-token', { token }),
    getSmtpSettings: () => api.get<SmtpConfigResponse>('/api/admin/settings/smtp'),
    saveSmtpSettings: (data: SmtpConfig) => api.put<void>('/api/admin/settings/smtp', data),
    testSmtp: () => api.post<{ status: string }>('/api/admin/settings/smtp/test', {}),
    sendUserPassword: (userId: string) => api.post<{ status: string; email: string }>(`/api/admin/users/${userId}/send-password`, {}),
    resetUserPassword: (userId: string) => api.post<{ password: string; email: string }>(`/api/admin/users/${userId}/reset-password`, {}),
    resetUserMfa: (userId: string) => api.post<{ status: string }>(`/api/admin/users/${userId}/reset-mfa`, {}),
};

export interface UpdateStatus {
    deployed_sha: string | null;
    deployed_at: string | null;
    remote_sha: string | null;
    update_available: boolean;
    github_reachable: boolean;
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

export interface ZusatzKanal {
    name: string;
    kanal: string;
}

export interface Leitstelle {
    id: string;
    name: string;
    anrufgruppe: string;
    zusatz_kanaele: ZusatzKanal[];
    has_geometry: boolean;
}

export interface LeistelleDetail extends Leitstelle {
    geometry_geojson: object | null;
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
    create: (data: { name: string; anrufgruppe: string; zusatz_kanaele: ZusatzKanal[] }) =>
        api.post<Leitstelle>('/api/leitstellen/', data),
    update: (id: string, data: { name?: string; anrufgruppe?: string; zusatz_kanaele?: ZusatzKanal[] }) =>
        api.put<Leitstelle>(`/api/leitstellen/${id}`, data),
    delete: (id: string) => api.delete(`/api/leitstellen/${id}`),
    importBoundary: (id: string, file: File) =>
        uploadFile<Leitstelle>(`/api/leitstellen/${id}/boundary`, file),
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
