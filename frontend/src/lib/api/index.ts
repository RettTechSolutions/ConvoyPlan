import { api } from './client';
import type { Geometry } from 'geojson';

export interface Point { lat: number; lon: number }
export interface Vehicle {
	id: string; name: string; callsign: string | null; license_plate: string | null;
	height_cm: number | null; weight_kg: number | null; length_cm: number | null; convoy_role: string | null;
}
export interface Waypoint {
	id: string; name: string; type: string; lat: number | null; lon: number | null;
	planned_arrival: string | null; planned_departure: string | null;
	hold_duration_min: number; notes: string | null; order_index: number;
}
export interface ConvoyVehicleItem { vehicle: Vehicle; position: number }
export interface Convoy {
	id: string; name: string; organization: string | null; start_time: string | null;
	speed_urban_kmh: number; speed_rural_kmh: number; status: string;
	share_token: string; created_at: string;
	start_point: Point | null; end_point: Point | null;
	convoy_vehicles: ConvoyVehicleItem[]; waypoints: Waypoint[];
}
export interface RouteResult {
	id: string; convoy_id: string; distance_m: number | null; duration_s: number | null;
	routing_params: Record<string, unknown> | null; geojson: Geometry | null;
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
	create: (data: Partial<Convoy>) => api.post<Convoy>('/api/convoys/', data),
	get: (id: string) => api.get<Convoy>(`/api/convoys/${id}`),
	update: (id: string, data: Partial<Convoy>) => api.put<Convoy>(`/api/convoys/${id}`, data),
	delete: (id: string) => api.delete(`/api/convoys/${id}`),
	addVehicle: (id: string, vehicleId: string, position: number) =>
		api.post(`/api/convoys/${id}/vehicles`, { vehicle_id: vehicleId, position }),
	removeVehicle: (id: string, vehicleId: string) =>
		api.delete(`/api/convoys/${id}/vehicles/${vehicleId}`),
	createWaypoint: (id: string, data: Partial<Waypoint> & { lat: number; lon: number }) =>
		api.post<Waypoint>(`/api/convoys/${id}/waypoints`, data),
	updateWaypoint: (id: string, wpId: string, data: Partial<Waypoint>) =>
		api.put<Waypoint>(`/api/convoys/${id}/waypoints/${wpId}`, data),
	deleteWaypoint: (id: string, wpId: string) =>
		api.delete(`/api/convoys/${id}/waypoints/${wpId}`),
	calculateRoute: (id: string) =>
		api.post<RouteResult>(`/api/convoys/${id}/calculate-route`, {}),
	exportGpx: (id: string) => `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/api/convoys/${id}/export/gpx`,
	exportJson: (id: string) => `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/api/convoys/${id}/export/json`,
};

// Public share
export const shareApi = {
	get: (token: string) => api.get<{ name: string; organization: string | null; start_time: string | null; waypoints: Waypoint[]; geojson: Geometry | null }>(`/api/convoys/share/${token}`),
};
