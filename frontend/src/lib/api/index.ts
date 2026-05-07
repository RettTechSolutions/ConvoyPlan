import { api } from './client';
import type { Geometry } from 'geojson';

export interface Point { lat: number; lon: number }

export type RoadPreference = 'schnell' | 'bundesstrasse' | 'landstrasse';

export interface Vehicle {
	id: string; name: string; callsign: string | null; license_plate: string | null;
	height_cm: number | null; weight_kg: number | null; length_cm: number | null; convoy_role: string | null;
	tank_capacity_l: number | null; fuel_consumption_l100km: number | null;
	current_fuel_l: number | null; range_km: number | null;
}

export interface FuelStopPosition { lat: number; lon: number; }
export interface VehicleRangeInfo { name: string; callsign: string | null; range_km: number; }
export interface FuelAnalysis {
	vehicles_with_range: VehicleRangeInfo[];
	min_range_km: number | null;
	route_distance_km: number;
	fuel_stop_needed: boolean;
	fuel_stop_km: number | null;
	fuel_stop_position: FuelStopPosition | null;
	limiting_vehicle: string | null;
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

export interface RouteResult {
	id: string; convoy_id: string; distance_m: number | null; duration_s: number | null;
	routing_params: Record<string, unknown> | null; geojson: Geometry | null;
	fuel_analysis: FuelAnalysis | null;
}

export interface Organization {
	id: string; name: string; description: string | null;
	member_count: number; my_role: string;
}

export interface LageLayer {
	id: string; name: string; geojson_data: Record<string, unknown>;
	color: string; visible: boolean;
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

// Auth
export const authApi = {
	register: (email: string, password: string) => api.post('/api/auth/register', { email, password }),
	login: (email: string, password: string) =>
		api.post<{ access_token: string }>('/api/auth/login', { email, password }),
};

// Vehicles
export const vehiclesApi = {
	list: () => api.get<Vehicle[]>('/api/vehicles/'),
	create: (data: Partial<Vehicle>) => api.post<Vehicle>('/api/vehicles/', data),
	update: (id: string, data: Partial<Vehicle>) => api.put<Vehicle>(`/api/vehicles/${id}`, data),
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
	calculateRoute: (id: string) =>
		api.post<RouteResult>(`/api/convoys/${id}/calculate-route`, {}),
	findFuelStations: (id: string, lat: number, lon: number, radiusM = 3000) =>
		api.get<FuelStation[]>(`/api/convoys/${id}/fuel-stations?lat=${lat}&lon=${lon}&radius_m=${radiusM}`),
	listSubConvoys: (id: string) => api.get<Convoy[]>(`/api/convoys/${id}/sub-convoys`),
	createSubConvoy: (id: string, data: Record<string, unknown>) =>
		api.post<Convoy>(`/api/convoys/${id}/sub-convoys`, data),
	exportUrl: (id: string, format: 'gpx' | 'json' | 'pdf') =>
		`${typeof window !== 'undefined' ? `http://${window.location.hostname}:8000` : (import.meta.env.VITE_API_URL ?? 'http://localhost:8000')}/api/convoys/${id}/export/${format}`,
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
	addMember: (orgId: string, email: string, role: string) =>
		api.post(`/api/organizations/${orgId}/members`, { email, role }),
	removeMember: (orgId: string, userId: string) =>
		api.delete(`/api/organizations/${orgId}/members/${userId}`),
	delete: (orgId: string) => api.delete(`/api/organizations/${orgId}`),
};

// V2: Lage-Layer
export const lageApi = {
	list: (convoyId: string) => api.get<LageLayer[]>(`/api/convoys/${convoyId}/lage`),
	create: (convoyId: string, data: Omit<LageLayer, 'id'>) =>
		api.post<LageLayer>(`/api/convoys/${convoyId}/lage`, data),
	update: (convoyId: string, layerId: string, data: Partial<LageLayer>) =>
		api.put<LageLayer>(`/api/convoys/${convoyId}/lage/${layerId}`, data),
	delete: (convoyId: string, layerId: string) =>
		api.delete(`/api/convoys/${convoyId}/lage/${layerId}`),
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
	onlineStream: (): EventSource =>
		new EventSource(
			`http://${typeof window !== 'undefined' ? window.location.hostname : 'localhost'}:8000/api/users/online`
		),
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
