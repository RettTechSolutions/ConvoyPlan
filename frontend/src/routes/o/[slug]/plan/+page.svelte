<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import AppLogo from '$lib/components/AppLogo.svelte';
	import MapView from '$lib/components/MapView.svelte';
	import LocationSearch from '$lib/components/LocationSearch.svelte';
	import InfoPill from '$lib/components/InfoPill.svelte';
	import ShareLinkModal from '$lib/components/ShareLinkModal.svelte';
	import { get } from 'svelte/store';
	import { page } from '$app/stores';
	import { orgStore } from '$lib/stores/org';
	import { activeConvoy, activeRoute, convoys } from '$lib/stores/convoy';
	import { mapMode } from '$lib/stores/map';
	import {
		convoysApi, vehiclesApi, orgsApi, overpassApi, authApi, mfaApi,
		type Convoy, type Vehicle, type Organization, type OrgMember,
		type FuelAnalysis, type FuelStation, type Waypoint, type RoadPreference,
		type KanalwechselEntry,
	} from '$lib/api';
	import { getToken } from '$lib/api/client';
	import type { FeatureCollection, Geometry } from 'geojson';
	import { dndzone } from 'svelte-dnd-action';
	import { themeStore } from '$lib/stores/theme';
	import { versionStore } from '$lib/stores/version.svelte';
	import { pwaStore } from '$lib/stores/pwa';
	import InstallButton from '$lib/components/InstallButton.svelte';
	import QRCode from 'qrcode';

	// ── State ──────────────────────────────────────────────────────────
	let allVehicles = $state<Vehicle[]>([]);
	let convoyList = $state<Convoy[]>([]);
	let organizations = $state<Organization[]>([]);
	let selected = $state<Convoy | null>(null);
	// Route geojson is tracked in its own $state so Svelte 5 can reliably detect
	// changes on every recalculation (avoids issues with the `unknown` type not
	// being deeply proxied, which prevented the map from updating on re-clicks).
	let routeGeojson = $state<Geometry | null>(null);
	let route = $state<{ distance_m: number | null; duration_s: number | null; fuel_analysis: FuelAnalysis | null; kanalwechsel: KanalwechselEntry[] } | null>(null);
	let fuelStations = $state<FuelStation[]>([]);
	let showFuelStations = $state(false);
	let fuelStationsLoading = $state(false);

	// Derived from actual waypoints so recalculating the route doesn't reset them
	let fuelStopExists = $derived(
		(selected?.waypoints ?? []).some(wp => wp.halt_purpose === 'fuel')
	);
	let thStopsAdded = $derived(
		(selected?.waypoints ?? []).filter(wp =>
			wp.type === 'technical_stop' && wp.halt_purpose !== 'fuel'
		).length
	);
	let closures = $state<FeatureCollection | null>(null);
	let showClosures = $state(false);
	let mapCenter = $state<[number, number]>([10.0, 51.5]);
	let activeTab = $state<'convoy'|'fahrzeuge'|'wegpunkte'|'zeitplan'|'export'|'konto'>('convoy');
	let loading = $state(false);
	let dndWaypoints = $state<Waypoint[]>([]);
	let dndVehicles = $state<Vehicle[]>([]);
	let editingWpId = $state<string | null>(null);
	let editWpForm = $state({ name: '', type: 'waypoint', hold_duration_min: 0, halt_purpose: '', notes: '' });
	let sidebarOpen = $state(false);
	let error = $state('');

	// Theme toggle
	function toggleTheme() {
	    themeStore.toggle();
	}

	// Import state
	let importFile = $state<File | null>(null);
	let importFileInput = $state<HTMLInputElement | null>(null);
	let importMode = $state<'add' | 'replace'>('replace');
	let importResult = $state<{ waypoints_imported: number; route_stored: boolean } | null>(null);
	let importError = $state('');
	let importing = $state(false);

	// Org management
	let expandedOrgId = $state<string | null>(null);
	let orgMembers = $state<Record<string, OrgMember[]>>({});
	let orgAddForm = $state<Record<string, { email: string; role: string }>>({});
	let orgInviteForm = $state<Record<string, { email: string; password: string }>>({});
	let orgInviteError = $state<Record<string, string>>({});

	async function loadOrgMembers(orgId: string) {
		try {
			orgMembers = { ...orgMembers, [orgId]: await orgsApi.listMembers(orgId) };
		} catch { /* ignore */ }
	}

	async function toggleOrgExpand(orgId: string) {
		if (expandedOrgId === orgId) { expandedOrgId = null; return; }
		expandedOrgId = orgId;
		if (!orgAddForm[orgId]) orgAddForm = { ...orgAddForm, [orgId]: { email: '', role: 'beobachter' } };
		if (!orgInviteForm[orgId]) orgInviteForm = { ...orgInviteForm, [orgId]: { email: '', password: '' } };
		if (!orgMembers[orgId]) await loadOrgMembers(orgId);
	}

	async function inviteMember(orgId: string) {
		const form = orgInviteForm[orgId];
		if (!form?.email || !form?.password) return;
		try {
			await orgsApi.inviteMember(orgId, form.email, form.password);
			orgInviteForm = { ...orgInviteForm, [orgId]: { email: '', password: '' } };
			orgInviteError = { ...orgInviteError, [orgId]: '' };
			await loadOrgMembers(orgId);
		} catch (e: unknown) {
			orgInviteError = { ...orgInviteError, [orgId]: e instanceof Error ? e.message : 'Fehler' };
		}
	}

	// Forms
	let showVehicleForm = $state(false);
	let showConvoyForm = $state(false);
	let showEditConvoyForm = $state(false);
	let editConvoy = $state({ name:'', organization:'', organization_id:'', start_time:'', speed_urban_kmh:40, speed_rural_kmh:65, road_preference:'standard' as RoadPreference, spacing_urban_m:15, spacing_rural_m:50, spacing_motorway_m:100 });
	let showBefehlModal = $state(false);
	let showShareLinkModal = $state(false);
	let showSubConvoyForm = $state(false);
	let newVehicle = $state({ name:'', callsign:'', license_plate:'', height_cm:'', weight_kg:'', length_cm:'', convoy_role:'', tank_capacity_l:'', fuel_consumption_l100km:'', current_fuel_l:'' });
	let editingVehicleId = $state<string | null>(null);
	let editVehicleForm = $state({ name:'', callsign:'', license_plate:'', height_cm:'', weight_kg:'', length_cm:'', convoy_role:'', tank_capacity_l:'', fuel_consumption_l100km:'', current_fuel_l:'' });
	let newConvoy = $state(defaultConvoyForm());
	let newWpForm = $state({ name:'', type:'waypoint', hold_duration_min:0, halt_purpose:'' });
	let pendingWpClick = $state(false);
	let wizardStep = $state<0 | 1 | 2 | 3>(0);
	let wizardWpName = $state('');

	function defaultConvoyForm() {
		return { name:'', organization:'', organization_id:'', start_time:'', speed_urban_kmh:40, speed_rural_kmh:65, road_preference:'standard' as RoadPreference, spacing_urban_m:15, spacing_rural_m:50, spacing_motorway_m:100, lage:'', auftrag:'', marschform:'geschlossener_verband', ablaufpunkt:'', ablaufzeit:'', ablaufführer:'', versorgung:'', funkgruppe:'', anlagen:'' };
	}

	// ── Konto-Tab (Passwort & MFA) ─────────────────────────────────
	let pwForm = $state({ current: '', next: '', confirm: '' });
	let pwWorking = $state(false);
	let pwError = $state('');
	let pwSuccess = $state('');

	async function changePassword() {
		pwError = '';
		pwSuccess = '';
		if (!pwForm.current || !pwForm.next || !pwForm.confirm) {
			pwError = 'Bitte alle Felder ausfüllen';
			return;
		}
		if (pwForm.next !== pwForm.confirm) {
			pwError = 'Die neuen Passwörter stimmen nicht überein';
			return;
		}
		if (pwForm.next.length < 10) {
			pwError = 'Neues Passwort muss mindestens 10 Zeichen lang sein';
			return;
		}
		pwWorking = true;
		try {
			const res = await authApi.changePassword(pwForm.current, pwForm.next);
			// Backend rotates the token version on password change; keep this
			// session valid by storing the freshly issued token.
			if (res.access_token) {
				const slug = ($page.params as Record<string, string>).slug;
				orgStore.setToken(slug, res.access_token);
			}
			pwForm = { current: '', next: '', confirm: '' };
			pwSuccess = 'Passwort geändert.';
			setTimeout(() => { pwSuccess = ''; }, 4000);
		} catch (e: unknown) {
			pwError = e instanceof Error ? e.message : 'Fehler beim Ändern';
		} finally {
			pwWorking = false;
		}
	}

	let mfaEnabled = $state(false);
	let mfaSetupSecret = $state('');
	let mfaSetupQrDataUrl = $state('');
	let mfaSetupStep = $state<'idle' | 'setup' | 'confirm'>('idle');
	let mfaCode = $state('');
	let mfaWorking = $state(false);
	let mfaError = $state('');
	let mfaSuccess = $state('');
	let mfaLoaded = $state(false);

	async function loadMfaStatus() {
		try {
			const s = await mfaApi.status();
			mfaEnabled = s.mfa_enabled;
			mfaLoaded = true;
		} catch { /* ignore */ }
	}

	async function startMfaSetup() {
		mfaWorking = true;
		mfaError = '';
		try {
			const data = await mfaApi.setup();
			mfaSetupSecret = data.secret;
			mfaSetupQrDataUrl = await QRCode.toDataURL(data.provisioning_uri, { width: 200, margin: 1 });
			mfaSetupStep = 'setup';
		} catch (e: unknown) {
			mfaError = e instanceof Error ? e.message : 'Fehler beim Setup';
		} finally { mfaWorking = false; }
	}

	async function confirmMfa() {
		if (mfaCode.length < 6) return;
		mfaWorking = true;
		mfaError = '';
		try {
			await mfaApi.confirm(mfaCode);
			mfaEnabled = true;
			mfaSetupStep = 'idle';
			mfaCode = '';
			mfaSuccess = 'MFA erfolgreich aktiviert.';
			setTimeout(() => { mfaSuccess = ''; }, 4000);
		} catch (e: unknown) {
			mfaError = e instanceof Error ? e.message : 'Ungültiger Code';
		} finally { mfaWorking = false; }
	}

	async function disableMfa() {
		if (mfaCode.length < 6) return;
		mfaWorking = true;
		mfaError = '';
		try {
			await mfaApi.disable(mfaCode);
			mfaEnabled = false;
			mfaSetupStep = 'idle';
			mfaCode = '';
			mfaSuccess = 'MFA deaktiviert.';
			setTimeout(() => { mfaSuccess = ''; }, 4000);
		} catch (e: unknown) {
			mfaError = e instanceof Error ? e.message : 'Ungültiger Code';
		} finally { mfaWorking = false; }
	}

	function openKontoTab() {
		activeTab = 'konto';
		if (!mfaLoaded) loadMfaStatus();
	}

	// ── Init ──────────────────────────────────────────────────────────
	onMount(async () => {
		pwaStore.init();
		await loadData();
	});

	async function loadData() {
		try {
			[allVehicles, convoyList, organizations] = await Promise.all([
				vehiclesApi.list(), convoysApi.list(), orgsApi.list(),
			]);
			dndVehicles = [...allVehicles];
			convoys.set(convoyList);
			if (!selected && convoyList.length) selectConvoy(convoyList[0]);
		} catch { error = 'Fehler beim Laden'; }
	}

	function selectConvoy(c: Convoy) {
		selected = c;
		activeConvoy.set(c);
		route = null;
		routeGeojson = null;
		activeRoute.set(null);
		fuelStations = [];
		showFuelStations = false;
		loadStoredRoute(c.id);
	}

	// Load a previously calculated route from the backend so it survives
	// page reloads / app restarts. Each calculated route is persisted server-side.
	async function loadStoredRoute(convoyId: string) {
		try {
			const r = await convoysApi.getRoute(convoyId);
			// Guard against a slow response after the user switched convoys
			if (!r || !r.geojson || get(activeConvoy)?.id !== convoyId) return;
			routeGeojson = r.geojson;
			route = {
				distance_m: r.distance_m,
				duration_s: r.duration_s,
				fuel_analysis: r.fuel_analysis,
				kanalwechsel: r.kanalwechsel ?? [],
			};
			activeRoute.set(r);
		} catch { /* no stored route yet */ }
	}

	async function refreshConvoy() {
		if (!selected) return;
		selected = await convoysApi.get(selected.id);
		convoyList = convoyList.map(c => c.id === selected!.id ? selected! : c);
		convoys.set(convoyList);
		activeConvoy.set(selected);
	}

	// ── Convoy CRUD ─────────────────────────────────────────────────
	async function createConvoy() {
		try {
			const c = await convoysApi.create({
				name: newConvoy.name,
				organization: newConvoy.organization || undefined,
				organization_id: newConvoy.organization_id || undefined,
				start_time: newConvoy.start_time || undefined,
				speed_urban_kmh: newConvoy.speed_urban_kmh,
				speed_rural_kmh: newConvoy.speed_rural_kmh,
				road_preference: newConvoy.road_preference,
				spacing_urban_m: newConvoy.spacing_urban_m,
				spacing_rural_m: newConvoy.spacing_rural_m,
				spacing_motorway_m: newConvoy.spacing_motorway_m,
			});
			convoyList = [...convoyList, c];
			convoys.set(convoyList);
			selectConvoy(c);
			showConvoyForm = false;
			newConvoy = defaultConvoyForm();
			wizardStep = 1;
			mapMode.set('set-start');
		} catch { error = 'Konvoi konnte nicht erstellt werden'; }
	}

	function openEditConvoyForm() {
		if (!selected) return;
		editConvoy = {
			name: selected.name,
			organization: selected.organization ?? '',
			organization_id: selected.organization_id ?? '',
			start_time: selected.start_time ? new Date(selected.start_time).toISOString().slice(0, 16) : '',
			speed_urban_kmh: selected.speed_urban_kmh,
			speed_rural_kmh: selected.speed_rural_kmh,
			road_preference: selected.road_preference as RoadPreference,
			spacing_urban_m: selected.spacing_urban_m,
			spacing_rural_m: selected.spacing_rural_m,
			spacing_motorway_m: selected.spacing_motorway_m,
		};
		showEditConvoyForm = true;
	}

	async function deleteConvoy() {
		if (!selected) return;
		if (!confirm(`Marschverband „${selected.name}" wirklich löschen? Alle Wegpunkte, Fahrzeuge und die Route werden unwiderruflich entfernt.`)) return;
		try {
			await convoysApi.delete(selected.id);
			convoyList = convoyList.filter(c => c.id !== selected!.id);
			selected = convoyList[0] ?? null;
			activeConvoy.set(selected);
			showEditConvoyForm = false;
			route = null;
			routeGeojson = null;
			activeRoute.set(null);
		} catch { error = 'Marschverband konnte nicht gelöscht werden'; }
	}

	async function saveConvoyEdit() {
		if (!selected) return;
		try {
			await convoysApi.update(selected.id, {
				name: editConvoy.name,
				organization: editConvoy.organization || undefined,
				organization_id: editConvoy.organization_id || undefined,
				start_time: editConvoy.start_time || undefined,
				speed_urban_kmh: editConvoy.speed_urban_kmh,
				speed_rural_kmh: editConvoy.speed_rural_kmh,
				road_preference: editConvoy.road_preference,
				spacing_urban_m: editConvoy.spacing_urban_m,
				spacing_rural_m: editConvoy.spacing_rural_m,
				spacing_motorway_m: editConvoy.spacing_motorway_m,
			});
			await refreshConvoy();
			showEditConvoyForm = false;
		} catch { error = 'Einstellungen konnten nicht gespeichert werden'; }
	}

	// ── Vehicles ─────────────────────────────────────────────────────
	async function createVehicle() {
		try {
			const v = await vehiclesApi.create({
				...newVehicle,
				height_cm: newVehicle.height_cm ? Number(newVehicle.height_cm) : undefined,
				weight_kg: newVehicle.weight_kg ? Number(newVehicle.weight_kg) : undefined,
				length_cm: newVehicle.length_cm ? Number(newVehicle.length_cm) : undefined,
				tank_capacity_l: newVehicle.tank_capacity_l ? Number(newVehicle.tank_capacity_l) : undefined,
				fuel_consumption_l100km: newVehicle.fuel_consumption_l100km ? Number(newVehicle.fuel_consumption_l100km) : undefined,
				current_fuel_l: newVehicle.current_fuel_l ? Number(newVehicle.current_fuel_l) : undefined,
			} as never);
			allVehicles = [...allVehicles, v];
			dndVehicles = [...allVehicles];
			newVehicle = { name:'', callsign:'', license_plate:'', height_cm:'', weight_kg:'', length_cm:'', convoy_role:'', tank_capacity_l:'', fuel_consumption_l100km:'', current_fuel_l:'' };
			showVehicleForm = false;
		} catch { error = 'Fahrzeug konnte nicht erstellt werden'; }
	}

	function startEditVehicle(v: Vehicle) {
		editingVehicleId = v.id;
		editVehicleForm = {
			name: v.name,
			callsign: v.callsign ?? '',
			license_plate: v.license_plate ?? '',
			height_cm: v.height_cm != null ? String(v.height_cm) : '',
			weight_kg: v.weight_kg != null ? String(v.weight_kg) : '',
			length_cm: v.length_cm != null ? String(v.length_cm) : '',
			convoy_role: v.convoy_role ?? '',
			tank_capacity_l: v.tank_capacity_l != null ? String(v.tank_capacity_l) : '',
			fuel_consumption_l100km: v.fuel_consumption_l100km != null ? String(v.fuel_consumption_l100km) : '',
			current_fuel_l: v.current_fuel_l != null ? String(v.current_fuel_l) : '',
		};
	}

	async function saveEditVehicle() {
		if (!editingVehicleId) return;
		try {
			const updated = await vehiclesApi.update(editingVehicleId, {
				...editVehicleForm,
				height_cm: editVehicleForm.height_cm ? Number(editVehicleForm.height_cm) : null,
				weight_kg: editVehicleForm.weight_kg ? Number(editVehicleForm.weight_kg) : null,
				length_cm: editVehicleForm.length_cm ? Number(editVehicleForm.length_cm) : null,
				tank_capacity_l: editVehicleForm.tank_capacity_l ? Number(editVehicleForm.tank_capacity_l) : null,
				fuel_consumption_l100km: editVehicleForm.fuel_consumption_l100km ? Number(editVehicleForm.fuel_consumption_l100km) : null,
				current_fuel_l: editVehicleForm.current_fuel_l ? Number(editVehicleForm.current_fuel_l) : null,
			} as never);
			allVehicles = allVehicles.map(v => v.id === editingVehicleId ? updated : v);
			dndVehicles = [...allVehicles];
			editingVehicleId = null;
		} catch { error = 'Fahrzeug konnte nicht gespeichert werden'; }
	}

	let vehicleSonderfunktion = $state<Record<string, string>>({});

	async function addVehicleToConvoy(vehicleId: string) {
		if (!selected) return;
		try {
			const sf = vehicleSonderfunktion[vehicleId] || undefined;
			await convoysApi.addVehicle(selected.id, vehicleId, selected.convoy_vehicles.length, sf);
			await refreshConvoy();
		} catch { error = 'Fehler beim Hinzufügen'; }
	}

	async function deleteVehicle(id: string) {
		if (!confirm('Fahrzeug wirklich löschen?')) return;
		try {
			await vehiclesApi.delete(id);
			allVehicles = allVehicles.filter(v => v.id !== id);
			dndVehicles = dndVehicles.filter(v => v.id !== id);
			if (selected?.convoy_vehicles.some(cv => cv.vehicle.id === id)) await refreshConvoy();
		} catch { error = 'Fahrzeug konnte nicht gelöscht werden'; }
	}

	async function removeVehicleFromConvoy(vehicleId: string) {
		if (!selected) return;
		try {
			await convoysApi.removeVehicle(selected.id, vehicleId);
			await refreshConvoy();
		} catch { error = 'Fehler beim Entfernen'; }
	}

	// ── Map Click Handler ─────────────────────────────────────────────
	async function handleMapClick(lat: number, lon: number) {
		if (!selected) { error = 'Kein Verband ausgewählt'; return; }
		const mode = get(mapMode);
		try {
			if (mode === 'set-start') {
				await convoysApi.update(selected.id, { start_point: { lat, lon } });
				mapMode.set('idle');
				if (wizardStep === 1) { wizardStep = 2; mapMode.set('set-end'); }
			} else if (mode === 'set-end') {
				await convoysApi.update(selected.id, { end_point: { lat, lon } });
				mapMode.set('idle');
				if (wizardStep === 2) { wizardStep = 3; mapMode.set('add-waypoint'); }
			} else if (mode === 'add-waypoint') {
				const name = wizardStep === 3
					? (wizardWpName.trim() || `WP ${(selected.waypoints.length + 1)}`)
					: (newWpForm.name || prompt('Wegpunktname:') || `WP ${(selected.waypoints.length + 1)}`);
				await convoysApi.createWaypoint(selected.id, {
					name,
					type: wizardStep === 3 ? 'waypoint' : newWpForm.type,
					lat,
					lon,
					hold_duration_min: wizardStep === 3 ? 0 : newWpForm.hold_duration_min,
					halt_purpose: wizardStep === 3 ? undefined : (newWpForm.halt_purpose || undefined),
					order_index: selected.waypoints.length,
				});
				wizardWpName = '';
				if (wizardStep !== 3) mapMode.set('idle');
			}
			await refreshConvoy();
		} catch (e) {
			console.error('handleMapClick error:', e);
			error = e instanceof Error ? e.message : 'Fehler beim Setzen des Punkts';
		}
	}

	function handleMapMove(lat: number, lon: number) {
		mapCenter = [lat, lon];
	}

	function wizardSetPoint(lat: number, lon: number, _label: string) {
		handleMapClick(lat, lon);
	}

	function wizardSkip() {
		if (wizardStep === 1) { wizardStep = 2; mapMode.set('set-end'); }
		else if (wizardStep === 2) { wizardStep = 3; mapMode.set('add-waypoint'); }
		else if (wizardStep === 3) { wizardStep = 0; mapMode.set('idle'); }
	}

	function wizardFinish() {
		wizardStep = 0;
		mapMode.set('idle');
	}

	// ── Waypoint ────────────────────────────────────────────────────
	async function deleteWaypoint(wpId: string) {
		if (!selected) return;
		try {
			await convoysApi.deleteWaypoint(selected.id, wpId);
			await refreshConvoy();
		} catch {
			error = 'Wegpunkt konnte nicht gelöscht werden';
		}
	}

	function handleVehicleDndConsider(e: CustomEvent) {
		dndVehicles = e.detail.items;
	}

	async function handleVehicleDndFinalize(e: CustomEvent) {
		const reordered: Vehicle[] = (e.detail.items as Vehicle[]).map((v, i) => ({ ...v, order_index: i }));
		dndVehicles = reordered;
		allVehicles = reordered;
		try {
			await vehiclesApi.reorder(reordered.map(v => ({ id: v.id, order_index: v.order_index })));
		} catch {
			// revert
			dndVehicles = [...allVehicles];
		}
	}

	function handleDndConsider(e: CustomEvent) {
    dndWaypoints = e.detail.items;
  }

  async function handleDndFinalize(e: CustomEvent) {
    const reordered: Waypoint[] = (e.detail.items as Waypoint[]).map(
      (wp, i) => ({ ...wp, order_index: i })
    );
    dndWaypoints = reordered;
    const prevWaypoints = selected!.waypoints;
    selected = { ...selected!, waypoints: reordered };
    activeConvoy.set(selected!);
    try {
      await convoysApi.reorderWaypoints(
        selected!.id,
        reordered.map((wp) => ({ id: wp.id, order_index: wp.order_index })),
      );
    } catch {
      dndWaypoints = prevWaypoints;
      selected = { ...selected!, waypoints: prevWaypoints };
      activeConvoy.set(selected!);
    }
  }

  function startEditWp(wp: Waypoint) {
    editingWpId = wp.id;
    editWpForm = {
      name: wp.name,
      type: wp.type,
      hold_duration_min: wp.hold_duration_min,
      halt_purpose: wp.halt_purpose ?? '',
      notes: wp.notes ?? '',
    };
  }

  async function saveWp(wpId: string) {
    try {
      await convoysApi.updateWaypoint(selected!.id, wpId, {
        name: editWpForm.name,
        type: editWpForm.type,
        hold_duration_min: editWpForm.hold_duration_min,
        halt_purpose: editWpForm.type === 'technical_stop' ? (editWpForm.halt_purpose || null) : null,
        notes: editWpForm.notes || null,
      });
      editingWpId = null;
      await refreshConvoy();
    } catch {
      error = 'Wegpunkt konnte nicht gespeichert werden';
    }
  }

	// ── Route ────────────────────────────────────────────────────────
	async function calculateRoute() {
		if (!selected) return;
		loading = true; error = '';
		try {
			const r = await convoysApi.calculateRoute(selected.id);
			routeGeojson = r.geojson;
			route = { distance_m: r.distance_m, duration_s: r.duration_s, fuel_analysis: r.fuel_analysis, kanalwechsel: r.kanalwechsel ?? [] };
			fuelStations = [];
			showFuelStations = false;
			activeRoute.set(r);
			await refreshConvoy();
			activeTab = 'zeitplan';

			// Fuel stations and closures use the public Overpass API which can be
			// very slow — run them in the background AFTER releasing the loading
			// state, otherwise the calculate button stays disabled for up to a
			// minute and appears broken.
			if (r.fuel_analysis?.fuel_stop_needed && r.fuel_analysis.fuel_stop_position) {
				activeTab = 'convoy';
				void loadFuelStationsInBackground(selected.id, r.fuel_analysis.fuel_stop_position);
			}
			if (selected?.start_point) {
				void loadClosuresInBackground(selected.start_point.lat, selected.start_point.lon);
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Routing fehlgeschlagen';
		} finally { loading = false; }
	}

	async function loadFuelStationsInBackground(convoyId: string, pos: { lat: number; lon: number }) {
		fuelStationsLoading = true;
		try {
			fuelStations = await convoysApi.findFuelStations(convoyId, pos.lat, pos.lon, 8000);
			showFuelStations = fuelStations.length > 0;
		} catch { /* non-critical */ }
		finally { fuelStationsLoading = false; }
	}

	async function loadClosuresInBackground(lat: number, lon: number) {
		try {
			closures = await overpassApi.getClosures(lat, lon, 25000) as unknown as FeatureCollection;
			showClosures = closures.features.length > 0;
		} catch { /* closures optional */ }
	}

	// ── Fuel stations ────────────────────────────────────────────────
	async function searchFuelStations() {
		if (!selected || !route?.fuel_analysis?.fuel_stop_position) return;
		fuelStationsLoading = true;
		showFuelStations = false;
		try {
			const { lat, lon } = route.fuel_analysis.fuel_stop_position;
			fuelStations = await convoysApi.findFuelStations(selected.id, lat, lon, 5000);
			showFuelStations = true;
		} catch { error = 'Tankstellensuche fehlgeschlagen'; }
		finally { fuelStationsLoading = false; }
	}

	async function addFuelStopWaypoint(station: FuelStation) {
		if (!selected || !route?.fuel_analysis) return;
		const fa = route.fuel_analysis;
		const stopKm = fa.fuel_stop_km ?? 0;
		const holdMin = fa.recommended_stop_duration_min ?? 15;
		await convoysApi.createWaypoint(selected.id, {
			name: station.name,
			type: 'technical_stop',
			halt_purpose: 'fuel',
			lat: station.lat,
			lon: station.lon,
			hold_duration_min: holdMin,
			order_index: selected.waypoints.length,
			notes: `Tankstopp bei km ${stopKm} – ${station.brand ?? station.name}${station.opening_hours ? ' · ' + station.opening_hours : ''}`,
		});
		showFuelStations = false;
		fuelStations = [];
		await refreshConvoy();
		await calculateRoute();
	}

	async function doImport() {
		if (!importFile || !selected) return;
		const ext = importFile.name.split('.').pop()?.toLowerCase();
		const format = ext === 'gpx' ? 'gpx' : 'geojson';
		importing = true;
		importResult = null;
		importError = '';
		try {
			importResult = await convoysApi.importFile(selected.id, format, importFile, importMode);
			await refreshConvoy();
			if (importResult.route_stored) {
				await calculateRoute();
			}
		} catch (e: unknown) {
			importError = e instanceof Error ? e.message : 'Import fehlgeschlagen';
		} finally {
			importing = false;
			importFile = null;
			if (importFileInput) importFileInput.value = '';
		}
	}

	async function addTHStopWaypoint(halt: import('$lib/api').DurationHalt) {
		if (!selected) return;
		try {
			await convoysApi.createWaypoint(selected.id, {
				name: halt.is_rest ? `Rast (km ${halt.stop_km})` : `Technischer Halt (km ${halt.stop_km})`,
				type: 'technical_stop',
				halt_purpose: halt.is_rest ? 'rest' : null,
				lat: halt.stop_position?.lat ?? null,
				lon: halt.stop_position?.lon ?? null,
				hold_duration_min: halt.duration_min,
				order_index: selected.waypoints.length,
			});
			await refreshConvoy();
		} catch { error = 'Fehler beim Hinzufügen des Halts'; }
	}

	// ── Closures ─────────────────────────────────────────────────────
	async function toggleClosures() {
		if (closures && showClosures) { showClosures = false; return; }
		showClosures = false;
		try {
			const lat = selected?.start_point?.lat ?? mapCenter[0];
			const lon = selected?.start_point?.lon ?? mapCenter[1];
			closures = await overpassApi.getClosures(lat, lon) as unknown as FeatureCollection;
			showClosures = true;
		} catch { error = 'Sperrungsdaten nicht verfügbar'; }
	}

	// ── Helpers ─────────────────────────────────────────────────────
	function formatDuration(s: number | null) {
		if (!s) return '–';
		const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
		return h > 0 ? `${h} h ${m} min` : `${m} min`;
	}
	function formatTime(iso: string | null) {
		if (!iso) return '–';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}
	function logout() {
		const slug = ($page.params as Record<string, string>).slug;
		orgStore.removeToken(slug);
		orgStore.clear();
		goto(`/o/${slug}/login`);
	}

	let assignedIds = $derived(new Set(selected?.convoy_vehicles.map(cv => cv.vehicle.id) ?? []));

	// Marschbefehl edit form (Export tab)
	let befehlForm = $state({ marschform:'', ablaufpunkt:'', ablaufzeit:'', ablaufführer:'', lage:'', auftrag:'', versorgung:'', funkgruppe:'', anlagen:'' });
	let befehlSaving = $state(false);
	let befehlSaved = $state(false);

	$effect(() => {
		if (selected) {
			befehlForm = {
				marschform: selected.marschform ?? '',
				ablaufpunkt: selected.ablaufpunkt ?? '',
				ablaufzeit: selected.ablaufzeit ? new Date(selected.ablaufzeit).toISOString().slice(0,16) : '',
				ablaufführer: selected.ablaufführer ?? '',
				lage: selected.lage ?? '',
				auftrag: selected.auftrag ?? '',
				versorgung: selected.versorgung ?? '',
				funkgruppe: selected.funkgruppe ?? '',
				anlagen: selected.anlagen ?? '',
			};
		}
	});

	async function saveBefehlForm() {
		if (!selected) return;
		befehlSaving = true;
		befehlSaved = false;
		try {
			await convoysApi.update(selected.id, {
				marschform: befehlForm.marschform || null,
				ablaufpunkt: befehlForm.ablaufpunkt || null,
				ablaufzeit: befehlForm.ablaufzeit || null,
				ablaufführer: befehlForm.ablaufführer || null,
				lage: befehlForm.lage || null,
				auftrag: befehlForm.auftrag || null,
				versorgung: befehlForm.versorgung || null,
				funkgruppe: befehlForm.funkgruppe || null,
				anlagen: befehlForm.anlagen || null,
			});
			await refreshConvoy();
			befehlSaved = true;
			setTimeout(() => (befehlSaved = false), 2000);
		} catch { error = 'Speichern fehlgeschlagen'; }
		finally { befehlSaving = false; }
	}

	$effect(() => {
    if (selected) {
      dndWaypoints = [...selected.waypoints].sort((a, b) => a.order_index - b.order_index);
    }
  });
	async function downloadExport(format: 'gpx' | 'json' | 'pdf') {
		if (!selected) return;
		try {
			const token = getToken();
			const res = await fetch(`/api/convoys/${selected.id}/export/${format}`, {
				headers: token ? { 'Authorization': `Bearer ${token}` } : {},
			});
			if (!res.ok) { error = `Export fehlgeschlagen (${res.status})`; return; }
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `${selected.name}.${format}`;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			URL.revokeObjectURL(url);
		} catch { error = 'Export fehlgeschlagen'; }
	}

	const WP_TYPE_LABELS: Record<string, string> = {
		waypoint: 'Wegpunkt', stop: 'Halt',
		checkpoint: 'Kontrollpunkt', technical_stop: 'Techn. Halt',
	};
	const STATUS_LABELS: Record<string, string> = {
		planned: 'Geplant', en_route: 'Unterwegs',
		arrived: 'Angekommen', delayed: 'Verspätung',
	};
	const STATUS_COLORS: Record<string, string> = {
		planned: '#95a5a6', en_route: '#3498db',
		arrived: '#27ae60', delayed: '#E23D28',
	};
</script>

<div class="app" class:sidebar-open={sidebarOpen}>
	<!-- ── Mobile top bar (hidden on desktop via CSS) ── -->
	<div class="topbar">
		<button class="hamburger" onclick={() => (sidebarOpen = !sidebarOpen)} aria-expanded={sidebarOpen} aria-controls="sidebar" aria-label="Menü">☰</button>
		<span class="topbar-name">{selected?.name ?? 'ConvoyPlan'}</span>
		<div class="topbar-actions">
			<button class="btn-map" class:active={$mapMode === 'set-start'} onclick={() => mapMode.set($mapMode === 'set-start' ? 'idle' : 'set-start')} aria-label="Startpunkt setzen">📍</button>
			<button class="btn-map" class:active={$mapMode === 'set-end'} onclick={() => mapMode.set($mapMode === 'set-end' ? 'idle' : 'set-end')} aria-label="Zielpunkt setzen">🏁</button>
			<button class="btn-map" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')} aria-label="Wegpunkt hinzufügen">➕</button>
		</div>
	</div>

	<!-- ── Sidebar backdrop (mobile only, shown when sidebar is open) ── -->
	{#if sidebarOpen}
		<button class="sidebar-backdrop" onclick={() => (sidebarOpen = false)} aria-label="Menü schließen"></button>
	{/if}

	<!-- ── Sidebar ──────────────────────────────────────────────────── -->
	<aside id="sidebar" class="sidebar" class:open={sidebarOpen}>
		<div class="sidebar-header">
			<div class="logo-wrap"><AppLogo width={null} /></div>
			<div style="display:flex;align-items:center;gap:.5rem">
				{#if $orgStore?.user_role === 'admin'}
					<a href="/o/{($page.params as Record<string, string>).slug}/admin" class="admin-link">⚙ Admin</a>
				{/if}
				<button class="logout-btn" onclick={logout} title="Abmelden">✕</button>
			</div>
		</div>

		<!-- Convoy-Selektor -->
		<div class="convoy-selector">
			<select onchange={(e) => { const c = convoyList.find(x => x.id === (e.target as HTMLSelectElement).value); if (c) selectConvoy(c); }}>
				{#if convoyList.length === 0}<option value="">Kein Marschverband</option>{/if}
				{#each convoyList as c}
					<option value={c.id} selected={selected?.id === c.id}>
						{c.parent_convoy_id ? '  ↳ ' : ''}{c.name}
					</option>
				{/each}
			</select>
			<button class="btn-small" onclick={() => (showConvoyForm = true)}>+ Neu</button>
		</div>

		{#if error}
			<div class="error-bar">
				<span>{error}</span>
				<button onclick={() => (error = '')}>✕</button>
			</div>
		{/if}

		{#if wizardStep === 0}
			<!-- Primary planning tabs -->
			<div class="tabs">
				{#each [['convoy','Plan'],['wegpunkte','Wegpunkte'],['zeitplan','Zeitplan'],['export','Export']] as [tab, label]}
					<button class="tab" class:active={activeTab === tab} onclick={() => (activeTab = tab as typeof activeTab)}>{label}</button>
				{/each}
			</div>
			<!-- Verwaltung tabs -->
			<div class="tabs tabs-verwaltung">
				<span class="tabs-section-label">Verwaltung</span>
				<button class="tab" class:active={activeTab === 'fahrzeuge'} onclick={() => (activeTab = 'fahrzeuge')}>Fahrzeuge</button>
				<button class="tab" class:active={activeTab === 'konto'} onclick={openKontoTab}>Konto</button>
			</div>

			<div class="tab-content">

				<!-- ── TAB: Plan ── -->
				{#if activeTab === 'convoy' && selected}
					<div class="section">
						<div class="section-header" style="margin-top:0">
							<span>Marschverband</span>
							<button class="btn-small" onclick={openEditConvoyForm}>✎ Bearbeiten</button>
						</div>
						<p><strong>Organisation:</strong> {selected.organization ?? '–'}</p>
						<p><strong>Startzeit:</strong> {selected.start_time ? new Date(selected.start_time).toLocaleString('de-DE') : '–'}</p>
						<p><strong>Tempo:</strong> {selected.speed_urban_kmh} km/h (innerorts) / {selected.speed_rural_kmh} km/h (außerorts) · {{ standard: 'Standard', schnell: 'Schnellste', kuerzeste: 'Kürzeste', bundesstrasse: 'Standard (veraltet)', landstrasse: 'Standard (veraltet)' }[selected.road_preference] ?? selected.road_preference}</p>
						<p><strong>Abstände:</strong> {selected.spacing_urban_m} m / {selected.spacing_rural_m} m / {selected.spacing_motorway_m} m (i/a/BAB)</p>
						{#if selected.marschform}<p><strong>Marschform:</strong> {({ geschlossener_verband:'Geschlossener Verband', einzelgruppen:'Einzelgruppen', individuell:'Individuelle Anreise' })[selected.marschform] ?? selected.marschform}</p>{/if}
						{#if selected.ablaufpunkt}<p><strong>Ablaufpunkt:</strong> {selected.ablaufpunkt}</p>{/if}
						{#if selected.ablaufführer}<p><strong>Ablaufführer:</strong> {selected.ablaufführer}</p>{/if}
						{#if selected.funkgruppe}<p><strong>Funkgruppe:</strong> {selected.funkgruppe}</p>{/if}
						{#if selected.lage}<details><summary><strong>Lage</strong></summary><p class="detail-text">{selected.lage}</p></details>{/if}
						{#if selected.auftrag}<details><summary><strong>Auftrag</strong></summary><p class="detail-text">{selected.auftrag}</p></details>{/if}
						{#if selected.parent_convoy_id}
							<p class="tag-pill">Teilverband</p>
						{/if}
					</div>
					<div class="map-actions">
						<button class="btn-map" class:active={$mapMode === 'set-start'} onclick={() => mapMode.set($mapMode === 'set-start' ? 'idle' : 'set-start')}>📍 Start</button>
						<button class="btn-map" class:active={$mapMode === 'set-end'} onclick={() => mapMode.set($mapMode === 'set-end' ? 'idle' : 'set-end')}>🏁 Ziel</button>
						<button class="btn-map" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')}>➕ Wegpunkt</button>
					</div>
					{#if $mapMode === 'add-waypoint'}
						<div class="wp-quick-form">
							<input placeholder="Name" bind:value={newWpForm.name} />
							<select bind:value={newWpForm.type}>
								<option value="waypoint">Wegpunkt</option>
								<option value="stop">Halt</option>
								<option value="checkpoint">Kontrollpunkt</option>
								<option value="technical_stop">Techn. Halt</option>
							</select>
							{#if newWpForm.type === 'technical_stop'}
								<select bind:value={newWpForm.halt_purpose}>
									<option value="">Grund wählen…</option>
									<option value="fuel">Tanken</option>
									<option value="rest">Pause</option>
									<option value="maintenance">Wartung</option>
									<option value="other">Sonstiges</option>
								</select>
							{/if}
							<input type="number" placeholder="Haltezeit (min)" bind:value={newWpForm.hold_duration_min} min="0" />
							<p class="hint">Jetzt auf Karte klicken ↗</p>
						</div>
					{/if}
					<div class="route-actions">
						<button class="btn-primary" onclick={calculateRoute} disabled={loading}>
							{loading ? 'Berechne…' : '🗺 Route berechnen'}
						</button>
						{#if route}
							<p class="route-info">{((route.distance_m ?? 0) / 1000).toFixed(1)} km · {formatDuration(route.duration_s)}</p>
							{#if route.fuel_analysis?.fuel_stop_needed && !fuelStopExists}
								<div class="fuel-warning">
									<p class="fuel-rec-title">⛽ Tankstopp empfohlen</p>
									<p class="fuel-detail">
										<strong>{route.fuel_analysis.limiting_vehicle}</strong> erreicht das Ziel nicht ohne Tanken:
										Reichweite <strong>{route.fuel_analysis.min_range_km} km</strong>,
										Routenlänge <strong>{route.fuel_analysis.route_distance_km} km</strong>.
									</p>
									<p class="fuel-detail">
										Empfohlener Stopp bei ca. <strong>km {route.fuel_analysis.fuel_stop_km}</strong>
										(80 % der Reichweite als Sicherheitspuffer) —
										geplante Haltezeit <strong>{route.fuel_analysis.recommended_stop_duration_min} min</strong>
										({selected?.convoy_vehicles.length ?? '?'} KFZ →
										{Math.ceil((selected?.convoy_vehicles.length ?? 1) / 3)} × 15 min).
									</p>
									{#if route.fuel_analysis.has_default_values}
										<p class="fuel-defaults-note">
											ℹ {route.fuel_analysis.vehicles_without_data === 1 ? '1 Fahrzeug' : `${route.fuel_analysis.vehicles_without_data} Fahrzeuge`}
											ohne hinterlegte Verbrauchsdaten – Berechnung mit Standardwerten
											(7,5 L/100 km, 70 L Tank).
										</p>
									{/if}
									{#if fuelStationsLoading}
										<p class="hint">Suche Tankstellen…</p>
									{/if}
									{#if showFuelStations && fuelStations.length}
										<ul class="fuel-station-list">
											{#each fuelStations as s}
												<li class="fuel-station-item">
													<div>
														<strong>{s.name}</strong>
														{#if s.brand && s.brand !== s.name}<span class="tag">{s.brand}</span>{/if}
														<span class="tag">{(s.distance_m / 1000).toFixed(1)} km</span>
														{#if s.opening_hours}<span class="tag">{s.opening_hours}</span>{/if}
													</div>
													<button class="btn-small" onclick={() => addFuelStopWaypoint(s)}>+ Halt</button>
												</li>
											{/each}
										</ul>
									{:else if showFuelStations}
										<p class="hint">Keine Tankstellen in der Nähe gefunden.</p>
									{/if}
								</div>
							{:else if route.fuel_analysis?.min_range_km && !fuelStopExists}
								<p class="fuel-ok">
									✅ Reichweite ausreichend — {route.fuel_analysis.min_range_km} km
									(Route: {route.fuel_analysis.route_distance_km} km)
									{#if route.fuel_analysis.has_default_values}
										<span class="fuel-defaults-inline"> · Standardwerte</span>
									{/if}
								</p>
							{:else if route.fuel_analysis && route.fuel_analysis.vehicles_with_range.length === 0 && allVehicles.length > 0}
								<p class="hint" style="margin-top:.4rem">⚠ Keine Fahrzeuge im Verband – gehe zu <strong>Fahrzeuge</strong> und füge sie mit + hinzu, um die Reichweitenanalyse zu nutzen.</p>
							{/if}
							{#if route.fuel_analysis?.duration_halt_needed}
								{@const remaining = route.fuel_analysis.duration_halts.slice(thStopsAdded)}
								{#if remaining.length > 0}
									<div class="th-warning">
										<p class="th-title">🛑 Technische Halte empfohlen</p>
										<p class="th-detail">Marschdauer &gt; 3 h — WOLKE-Prüfung{route.fuel_analysis.rest_needed ? ' + Rast' : ''} einplanen:</p>
										<ul class="th-list">
											{#each remaining as halt}
												<li class="th-item">
													<div>
														<strong>{halt.is_rest ? '🛏 Rast' : '🔧 TH'}</strong>
														bei ca. km <strong>{halt.stop_km}</strong>
														— <strong>{halt.duration_min} min</strong>
														{#if halt.is_rest}<span class="tag th-rest-tag">Fahrerwechsel / Erholung</span>{:else}<span class="tag th-tag">WOLKE</span>{/if}
													</div>
													<button class="btn-small" onclick={() => addTHStopWaypoint(halt)}>+ Halt</button>
												</li>
											{/each}
										</ul>
									</div>
								{/if}
							{/if}
						{/if}
					</div>

					<!-- V2: Teilverband -->
					<div class="section" style="margin-top:.75rem">
						<div class="section-header">
							<strong>Teilverbände</strong>
							<button class="btn-small" onclick={() => (showSubConvoyForm = !showSubConvoyForm)}>+ Neu</button>
						</div>
						{#if showSubConvoyForm}
							<form class="inline-form" onsubmit={async (e) => {
								e.preventDefault();
								if (!selected) return;
								await convoysApi.createSubConvoy(selected.id, { name: newConvoy.name, speed_urban_kmh: 40, speed_rural_kmh: 65 });
								await loadData();
								showSubConvoyForm = false;
								newConvoy = { ...newConvoy, name: '' };
							}}>
								<input placeholder="Name des Teilverbands *" bind:value={newConvoy.name} required />
								<button type="submit">Erstellen</button>
							</form>
						{/if}
						{#each convoyList.filter(c => c.parent_convoy_id === selected?.id) as sub}
							<div class="sub-convoy-item" onclick={() => selectConvoy(sub)}>
								↳ {sub.name}
							</div>
						{/each}
					</div>
				{/if}

				<!-- ── TAB: Fahrzeuge ── -->
				{#if activeTab === 'fahrzeuge'}
					<div class="section">
						<div class="section-header">
							<strong>Meine Fahrzeuge</strong>
							<button class="btn-small" onclick={() => (showVehicleForm = !showVehicleForm)}>+ Neu</button>
						</div>
						{#if showVehicleForm}
							<form class="inline-form" onsubmit={(e) => { e.preventDefault(); createVehicle(); }}>
								<input placeholder="Name *" bind:value={newVehicle.name} required />
								<input placeholder="Funkrufname" bind:value={newVehicle.callsign} />
								<input placeholder="Kennzeichen" bind:value={newVehicle.license_plate} />
								<input placeholder="Höhe (cm)" type="number" bind:value={newVehicle.height_cm} />
								<input placeholder="Gewicht (kg)" type="number" bind:value={newVehicle.weight_kg} />
								<input placeholder="Länge (cm)" type="number" bind:value={newVehicle.length_cm} />
								<input placeholder="Funktion im Konvoi" bind:value={newVehicle.convoy_role} />
								<hr style="border-color:rgba(255,255,255,.15);margin:.2rem 0" />
								<input placeholder="Tankvolumen (Liter)" type="number" step="0.1" min="0" bind:value={newVehicle.tank_capacity_l} />
								<input placeholder="Verbrauch (l/100 km)" type="number" step="0.1" min="0" bind:value={newVehicle.fuel_consumption_l100km} />
								<input placeholder="Aktueller Füllstand (Liter)" type="number" step="0.1" min="0" bind:value={newVehicle.current_fuel_l} />
								<button type="submit">Speichern</button>
							</form>
						{/if}
						<ul
							class="vehicle-list"
							use:dndzone={{ items: dndVehicles, flipDurationMs: 200 }}
							onconsider={handleVehicleDndConsider}
							onfinalize={handleVehicleDndFinalize}
						>
							{#each dndVehicles as v (v.id)}
								<li class="vehicle-item" style="flex-direction:column;align-items:stretch;gap:.3rem">
									{#if editingVehicleId === v.id}
										<form class="inline-form" onsubmit={(e) => { e.preventDefault(); saveEditVehicle(); }}>
											<input placeholder="Name *" bind:value={editVehicleForm.name} required />
											<input placeholder="Funkrufname" bind:value={editVehicleForm.callsign} />
											<input placeholder="Kennzeichen" bind:value={editVehicleForm.license_plate} />
											<input placeholder="Höhe (cm)" type="number" bind:value={editVehicleForm.height_cm} />
											<input placeholder="Gewicht (kg)" type="number" bind:value={editVehicleForm.weight_kg} />
											<input placeholder="Länge (cm)" type="number" bind:value={editVehicleForm.length_cm} />
											<input placeholder="Funktion im Konvoi" bind:value={editVehicleForm.convoy_role} />
											<hr style="border-color:rgba(255,255,255,.15);margin:.2rem 0" />
											<input placeholder="Tankvolumen (Liter)" type="number" step="0.1" min="0" bind:value={editVehicleForm.tank_capacity_l} />
											<input placeholder="Verbrauch (l/100 km)" type="number" step="0.1" min="0" bind:value={editVehicleForm.fuel_consumption_l100km} />
											<input placeholder="Aktueller Füllstand (Liter)" type="number" step="0.1" min="0" bind:value={editVehicleForm.current_fuel_l} />
											<div style="display:flex;gap:.4rem">
												<button type="submit" style="flex:1">Speichern</button>
												<button type="button" class="btn-small danger" onclick={() => editingVehicleId = null}>Abbrechen</button>
											</div>
										</form>
									{:else}
										<div style="display:flex;justify-content:space-between;align-items:center">
											<div>
												<strong>{v.name}</strong>
												{#if v.callsign}<span class="tag">{v.callsign}</span>{/if}
												{#if v.license_plate}<span class="tag">{v.license_plate}</span>{/if}
												{#if v.range_km != null}
													<span class="tag" class:fuel-tag={!v.range_uses_defaults} class:fuel-tag-default={v.range_uses_defaults} title={v.range_uses_defaults ? 'Reichweite basiert auf Standardwerten (7,5 l/100km, 70 l)' : ''}>⛽ {v.range_uses_defaults ? '~' : ''}{v.range_km} km</span>
												{/if}
											</div>
											<div style="display:flex;gap:.3rem;align-items:center">
												<button class="btn-small" title="Bearbeiten" onclick={() => startEditVehicle(v)}>✏️</button>
												<button class="btn-small danger" title="Löschen" onclick={() => deleteVehicle(v.id)}>🗑</button>
												{#if selected}
													{#if assignedIds.has(v.id)}
														<button class="btn-small danger" onclick={() => removeVehicleFromConvoy(v.id)}>–</button>
													{:else}
														<button class="btn-small" onclick={() => addVehicleToConvoy(v.id)}>+</button>
													{/if}
												{/if}
											</div>
										</div>
										{#if selected && !assignedIds.has(v.id)}
											<select class="sf-select" bind:value={vehicleSonderfunktion[v.id]}>
												<option value="">Sonderfunktion…</option>
												<option value="spitzenführer">Spitzenführer</option>
												<option value="schließender">Schließender (Ablaufführer)</option>
												<option value="sanitaet">Sanitätsdienstliche Absicherung</option>
												<option value="führungsfahrzeug">Führungsfahrzeug</option>
											</select>
										{/if}
									{/if}
								</li>
							{/each}
						</ul>
						{#if selected?.convoy_vehicles.length}
							<div class="section-header" style="margin-top:.75rem"><strong>Im Verband (Marschfolge)</strong></div>
							<ol class="vehicle-list">
								{#each selected.convoy_vehicles as cv}
									<li class="vehicle-item convoy-vehicle-row">
										<div class="veh-left">
											<span class="veh-pos">{cv.position + 1}.</span>
											<div>
												<span>{cv.vehicle.name}</span>
												{#if cv.vehicle.callsign}<span class="tag">{cv.vehicle.callsign}</span>{/if}
												{#if cv.sonderfunktion}
													<span class="tag sonder">{({ spitzenführer:'Spitze', schließender:'Schließ.', sanitaet:'San.', ablaufführer:'Ablauf', führungsfahrzeug:'Führung' })[cv.sonderfunktion] ?? cv.sonderfunktion}</span>
												{/if}
											</div>
										</div>
										<span class="status-dot" style="background:{STATUS_COLORS[cv.vehicle_status] ?? '#95a5a6'}" title={STATUS_LABELS[cv.vehicle_status] ?? cv.vehicle_status}></span>
									</li>
								{/each}
							</ol>
							<p class="hint" style="margin-top:.4rem">Position 1 = Spitzenführer, letztes Fahrzeug = Schließender</p>
						{/if}
					</div>
				{/if}

				<!-- ── TAB: Konto ── -->
				{#if activeTab === 'konto'}
					<div class="section">
						<div class="section-header" style="margin-top:0">
							<strong>Passwort ändern</strong>
						</div>
						{#if pwError}
							<p class="error-bar">{pwError}</p>
						{/if}
						{#if pwSuccess}
							<p class="success-bar">{pwSuccess}</p>
						{/if}
						<form class="inline-form" onsubmit={(e) => { e.preventDefault(); changePassword(); }}>
							<input type="password" placeholder="Aktuelles Passwort" autocomplete="current-password" bind:value={pwForm.current} required />
							<input type="password" placeholder="Neues Passwort (min. 8 Zeichen)" autocomplete="new-password" bind:value={pwForm.next} required minlength="8" />
							<input type="password" placeholder="Neues Passwort bestätigen" autocomplete="new-password" bind:value={pwForm.confirm} required minlength="8" />
							<button type="submit" disabled={pwWorking}>{pwWorking ? '…' : 'Passwort ändern'}</button>
						</form>
					</div>

					<div class="section">
						<div class="section-header">
							<strong>Zwei-Faktor-Authentifizierung (MFA)</strong>
						</div>
						{#if mfaError}
							<p class="error-bar">{mfaError}</p>
						{/if}
						{#if mfaSuccess}
							<p class="success-bar">{mfaSuccess}</p>
						{/if}

						{#if mfaSetupStep === 'idle'}
							<p>
								<strong>Status:</strong>
								{#if mfaEnabled}
									<span class="tag fuel-tag">Aktiv ✓</span>
								{:else}
									<span class="tag">Nicht aktiv</span>
								{/if}
							</p>

							{#if mfaEnabled}
								<p class="hint">MFA ist aktiv. Zum Deaktivieren bitte aktuellen Code aus deiner Authenticator-App eingeben:</p>
								<div class="inline-form" style="flex-direction:row;gap:.4rem;align-items:center">
									<input
										type="text"
										inputmode="numeric"
										maxlength="6"
										placeholder="000000"
										bind:value={mfaCode}
										autocomplete="one-time-code"
										style="flex:1;letter-spacing:.2em;text-align:center"
									/>
									<button class="btn-small danger" onclick={disableMfa} disabled={mfaWorking || mfaCode.length < 6}>
										{mfaWorking ? '…' : 'Deaktivieren'}
									</button>
								</div>
							{:else}
								<p class="hint">MFA schützt dein Konto mit einem zweiten Faktor (Authenticator-App wie Authy, Google Authenticator).</p>
								<button onclick={startMfaSetup} disabled={mfaWorking}>
									{mfaWorking ? '…' : 'MFA einrichten'}
								</button>
							{/if}

						{:else if mfaSetupStep === 'setup'}
							<p class="hint">Scanne den QR-Code mit einer Authenticator-App oder gib den Secret manuell ein.</p>
							{#if mfaSetupQrDataUrl}
								<img src={mfaSetupQrDataUrl} alt="MFA QR Code" style="display:block;margin:.5rem auto;background:#fff;padding:.5rem;border-radius:6px" />
							{/if}
							<p style="word-break:break-all;font-family:monospace;font-size:var(--text-xs);background:var(--surface-2);padding:.5rem;border-radius:4px">
								{mfaSetupSecret}
							</p>
							<p class="hint">Danach Code eingeben um MFA zu aktivieren:</p>
							<div class="inline-form" style="flex-direction:row;gap:.4rem;align-items:center">
								<input
									type="text"
									inputmode="numeric"
									maxlength="6"
									placeholder="000000"
									bind:value={mfaCode}
									autocomplete="one-time-code"
									style="flex:1;letter-spacing:.2em;text-align:center"
								/>
								<button onclick={confirmMfa} disabled={mfaWorking || mfaCode.length < 6}>
									{mfaWorking ? '…' : 'Bestätigen'}
								</button>
								<button class="btn-small" onclick={() => { mfaSetupStep = 'idle'; mfaCode = ''; }}>Abbrechen</button>
							</div>
						{/if}
					</div>
				{/if}

				<!-- ── TAB: Wegpunkte ── -->
				{#if activeTab === 'wegpunkte' && selected}
					<div class="section">
						<div class="section-header">
							<strong>Wegpunkte</strong>
							<button class="btn-small" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')}>
								+ Karte
							</button>
						</div>
						{#if !selected.waypoints.length}
							<p class="hint">Noch keine Wegpunkte.</p>
						{/if}
						<ul
							class="wp-list"
							use:dndzone={{ items: dndWaypoints, flipDurationMs: 200 }}
							onconsider={handleDndConsider}
							onfinalize={handleDndFinalize}
						>
							{#each dndWaypoints as wp (wp.id)}
								<li class="wp-item">
									<div class="wp-main">
										<strong>{wp.name}</strong>
										<span class="tag">{WP_TYPE_LABELS[wp.type] ?? wp.type}</span>
										{#if wp.halt_purpose && wp.halt_purpose !== 'technical'}<span class="tag orange">{wp.halt_purpose}</span>{/if}
										{#if wp.hold_duration_min > 0}<span class="tag">{wp.hold_duration_min} min</span>{/if}
									</div>
									<div class="wp-actions">
										<button class="btn-small" onclick={() => startEditWp(wp)} title="Bearbeiten">✎</button>
										<button class="btn-small danger" onclick={() => deleteWaypoint(wp.id)}>✕</button>
									</div>
									{#if editingWpId === wp.id}
										<div class="wp-edit-form">
											<input bind:value={editWpForm.name} placeholder="Name" />
											<select bind:value={editWpForm.type}>
												<option value="waypoint">Wegpunkt</option>
												<option value="stop">Halt</option>
												<option value="checkpoint">Kontrollpunkt</option>
												<option value="technical_stop">Techn. Halt</option>
											</select>
											{#if editWpForm.type === 'technical_stop'}
												<select bind:value={editWpForm.halt_purpose}>
													<option value="">Zweck wählen…</option>
													<option value="fuel">Tanken</option>
													<option value="rest">Pause</option>
													<option value="maintenance">Wartung</option>
													<option value="other">Sonstiges</option>
												</select>
											{/if}
											<input type="number" bind:value={editWpForm.hold_duration_min} min="0" placeholder="Haltezeit (min)" />
											<input bind:value={editWpForm.notes} placeholder="Notiz (optional)" />
											<div class="wp-edit-actions">
												<button class="btn-small" onclick={() => saveWp(wp.id)}>Speichern</button>
												<button class="btn-small" onclick={() => (editingWpId = null)}>Abbrechen</button>
											</div>
										</div>
									{/if}
								</li>
							{/each}
						</ul>
					</div>
				{/if}

				<!-- ── TAB: Zeitplan ── -->
				{#if activeTab === 'zeitplan' && selected}
					<div class="section">
						<strong>Zeitplan</strong>
						{#if selected.waypoints.some(w => w.planned_arrival)}
							<table class="schedule-table">
								<thead><tr><th>Wegpunkt</th><th>Ankunft</th><th>Abfahrt</th></tr></thead>
								<tbody>
									{#each selected.waypoints as wp}
										<tr>
											<td>{wp.name} {#if wp.type === 'technical_stop'}<span class="tag orange">Techn.</span>{/if}</td>
											<td>{formatTime(wp.planned_arrival)}</td>
											<td>{formatTime(wp.planned_departure)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{:else}
							<p class="hint">Zeitplan wird nach Routenberechnung angezeigt.</p>
						{/if}
						{#if route?.kanalwechsel?.length}
							<div class="kw-section">
								<strong>Kanalwechsel</strong>
								<table class="schedule-table kw-table">
									<thead><tr><th>km</th><th>Leitstelle</th><th>Anrufgruppe</th></tr></thead>
									<tbody>
										{#each route.kanalwechsel as kw}
											<tr>
												<td>{kw.km.toFixed(1)}</td>
												<td>📡 {kw.leitstelle_name}</td>
												<td><code>{kw.anrufgruppe}</code></td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}
					</div>
				{/if}

				<!-- ── TAB: Export ── -->
				{#if activeTab === 'export' && selected}
					<div class="section">
						<strong>Exportieren</strong>
						<div class="export-grid">
							<button class="btn-export" onclick={() => downloadExport('gpx')}>📍 GPX herunterladen</button>
							<button class="btn-export" onclick={() => downloadExport('json')}>📄 JSON herunterladen</button>
							<button class="btn-export" onclick={() => (showBefehlModal = true)}>📋 Marschbefehl</button>
							<button class="btn-export" onclick={() => navigator.clipboard.writeText(`${window.location.origin}/share/${selected?.share_token}`)}>🔗 Link kopieren</button>
						</div>
						<div class="section-header" style="margin-top:1rem"><strong>Live-Tracking</strong></div>
						<div class="export-grid">
							<a class="btn-export" href="/o/{$page.params.slug}/tracking/{selected.id}" target="_blank">🔴 Tracking-Ansicht öffnen</a>
							<button class="btn-export" onclick={() => (showShareLinkModal = true)}>🔗 Öffentlich teilen (QR / Passwort)</button>
						</div>
						<div class="section-header" style="margin-top:1rem"><strong>Sperrungen & Baustellen</strong></div>
						<button class="btn-export" class:active={showClosures} onclick={toggleClosures}>
							{showClosures ? '🚧 Sperrungen ausblenden' : '🚧 Sperrungen laden'}
						</button>
						<div class="section-header" style="margin-top:1rem"><strong>Import</strong></div>
						<div style="display:flex;flex-direction:column;gap:.5rem">
							<input
								type="file"
								accept=".gpx,.geojson,.json"
								bind:this={importFileInput}
								disabled={importing}
								onchange={(e) => { importFile = (e.target as HTMLInputElement).files?.[0] ?? null; importResult = null; importError = ''; }}
								style="font-size:.8rem"
							/>
							<fieldset style="border:none;padding:0;margin:0;display:flex;gap:1rem;font-size:.85rem">
								<legend style="float:left;font-size:.85rem;margin-right:.5rem;color:#aaa">Modus:</legend>
								<label style="display:flex;gap:.3rem;align-items:center;cursor:pointer">
									<input type="radio" bind:group={importMode} value="replace" /> Ersetzen
								</label>
								<label style="display:flex;gap:.3rem;align-items:center;cursor:pointer">
									<input type="radio" bind:group={importMode} value="add" /> Hinzufügen
								</label>
							</fieldset>
							<button
								class="btn-export"
								onclick={doImport}
								disabled={!importFile || importing}
							>
								{importing ? 'Importiere…' : '⬆ Importieren'}
							</button>
							{#if importResult}
								<p role="status" aria-live="polite" style="font-size:.8rem;color:#2e7d32;margin:0">
									{importResult.waypoints_imported} Wegpunkt{importResult.waypoints_imported !== 1 ? 'e' : ''} importiert
									{importResult.route_stored ? '· Route auf Karte geladen' : ''}
								</p>
							{/if}
							{#if importError}
								<p role="alert" aria-live="assertive" style="font-size:.8rem;color:#f44336;margin:0">{importError}</p>
							{/if}
						</div>
					</div>
				{/if}

			</div>
		{:else}
			<!-- Wizard -->
			<div class="wizard">
				<div class="wizard-steps">
					<span class:active={wizardStep === 1}>1</span>
					<span class="sep">›</span>
					<span class:active={wizardStep === 2}>2</span>
					<span class="sep">›</span>
					<span class:active={wizardStep === 3}>3</span>
				</div>

				{#if wizardStep === 1}
					<h3 class="wizard-title">Startpunkt setzen</h3>
					<LocationSearch
						placeholder="Startort suchen…"
						onSelect={wizardSetPoint}
					/>
					<p class="hint">oder direkt auf die Karte klicken ↗</p>
					<button class="btn-skip" onclick={wizardSkip}>Überspringen →</button>

				{:else if wizardStep === 2}
					<h3 class="wizard-title">Zielpunkt setzen</h3>
					<LocationSearch
						placeholder="Zielort suchen…"
						onSelect={wizardSetPoint}
					/>
					<p class="hint">oder direkt auf die Karte klicken ↗</p>
					<button class="btn-skip" onclick={wizardSkip}>Überspringen →</button>

				{:else if wizardStep === 3}
					<h3 class="wizard-title">Wegpunkte hinzufügen</h3>
					<input
						class="wp-name-input"
						placeholder="Name (optional)"
						bind:value={wizardWpName}
					/>
					<LocationSearch
						placeholder="Wegpunkt suchen…"
						onSelect={wizardSetPoint}
					/>
					<p class="hint">oder auf die Karte klicken ↗</p>
					{#if selected?.waypoints?.length}
						<ul class="wizard-wp-list">
							{#each selected.waypoints as wp}
								<li>📍 {wp.name}</li>
							{/each}
						</ul>
					{/if}
					<button class="btn-primary" onclick={wizardFinish}>Fertig ✓</button>
					<button class="btn-skip" onclick={wizardSkip}>Überspringen →</button>
				{/if}
			</div>
		{/if}
	<div class="sidebar-footer">
		<button class="theme-toggle" onclick={toggleTheme} aria-label="Theme umschalten">
			{$themeStore === 'dark' ? '☀' : '☾'}
			<span>{$themeStore === 'dark' ? 'Light' : 'Dark'}</span>
		</button>
		<InstallButton />
		<span class="app-version">
			v{__APP_VERSION__}
			{#if versionStore.data.update_available}
				<a
					class="update-hint"
					href="https://github.com/RettTechSolutions/ConvoyPlan/releases/latest"
					target="_blank"
					rel="noopener noreferrer"
					title="Neue Version {versionStore.data.latest} verfügbar"
				>· Update verfügbar</a>
			{/if}
		</span>
	</div>
	</aside>

	<!-- ── Karte ─────────────────────────────────────────────────────── -->
	<main class="map-area">
		<!-- FAB route button shown on mobile only -->
		<button class="fab-route" onclick={calculateRoute} disabled={loading}>
			{loading ? 'Berechne…' : '🗺 Route'}
		</button>
		{#if $mapMode !== 'idle'}
			<div class="map-hint-bar">
				{#if $mapMode === 'set-start'}Start setzen – auf Karte klicken{/if}
				{#if $mapMode === 'set-end'}Ziel setzen – auf Karte klicken{/if}
				{#if $mapMode === 'add-waypoint'}Wegpunkt setzen – auf Karte klicken{/if}
				<button onclick={() => mapMode.set('idle')}>Abbrechen</button>
			</div>
		{/if}

		<InfoPill
			startPoint={selected?.start_point}
			closuresCount={closures?.features?.length ?? 0}
			onShowClosures={toggleClosures}
		/>

		<MapView
			startPoint={selected?.start_point}
			endPoint={selected?.end_point}
			waypoints={selected?.waypoints ?? []}
			routeGeojson={routeGeojson}
			closuresGeojson={showClosures ? closures : null}
			onMapClick={handleMapClick}
			onMapMove={handleMapMove}
		/>
	</main>
</div>

<!-- ── Modal: Marschbefehl ausfüllen ──────────────────────────────── -->
{#if showBefehlModal}
	<div class="modal-backdrop befehl-backdrop" onclick={() => (showBefehlModal = false)}>
		<div class="modal befehl-modal" onclick={(e) => e.stopPropagation()}>
			<div class="befehl-modal-header">
				<h2>Marschbefehl</h2>
				<span class="befehl-convoy-name">{selected?.name}</span>
				<button class="modal-close" onclick={() => (showBefehlModal = false)}>✕</button>
			</div>

			<div class="befehl-modal-body">
				<!-- Marschbewegung -->
				<div class="befehl-section">
					<div class="befehl-section-title">Marschbewegung</div>
					<div class="befehl-row">
						<label class="bf-label">
							Marschform
							<select bind:value={befehlForm.marschform}>
								<option value="">– nicht angegeben –</option>
								<option value="geschlossener_verband">Geschlossener Gesamtverband</option>
								<option value="einzelgruppen">Einzelgruppen</option>
								<option value="individuell">Individuelle Anreise</option>
							</select>
						</label>
					</div>
				</div>

				<!-- Ablaufpunkt -->
				<div class="befehl-section">
					<div class="befehl-section-title">Ablaufpunkt</div>
					<div class="befehl-row befehl-row-3">
						<label class="bf-label">
							Ablaufpunkt (Ort)
							<input type="text" placeholder="z.B. Parkplatz Messehalle Nord" bind:value={befehlForm.ablaufpunkt} />
						</label>
						<label class="bf-label">
							Ablaufzeit
							<input type="datetime-local" bind:value={befehlForm.ablaufzeit} />
						</label>
						<label class="bf-label">
							Ablaufführer
							<input type="text" placeholder="Name / Rufname" bind:value={befehlForm.ablaufführer} />
						</label>
					</div>
				</div>

				<!-- Führung & Verbindung -->
				<div class="befehl-section">
					<div class="befehl-section-title">Führung & Verbindung</div>
					<div class="befehl-row">
						<label class="bf-label">
							Funkgruppe
							<input type="text" placeholder="z.B. KatS Bayern 1" bind:value={befehlForm.funkgruppe} />
						</label>
					</div>
					{#if route?.kanalwechsel?.length}
						<div class="befehl-row">
							<label>Kanalwechsel</label>
							<table class="kw-befehl-table">
								<thead><tr><th>km</th><th>Leitstelle</th><th>Anrufgruppe</th></tr></thead>
								<tbody>
									{#each route.kanalwechsel as kw}
										<tr>
											<td>{kw.km.toFixed(1)}</td>
											<td>📡 {kw.leitstelle_name}</td>
											<td><code>{kw.anrufgruppe}</code></td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</div>

				<!-- 1. Lage -->
				<div class="befehl-section">
					<div class="befehl-section-title">1. Lage</div>
					<textarea class="befehl-textarea" rows="4" placeholder="Lagebeschreibung – Eigene und feindliche/gegnerische Kräfte, Lage der Bevölkerung, zivile Behörden…" bind:value={befehlForm.lage}></textarea>
				</div>

				<!-- 2. Auftrag -->
				<div class="befehl-section">
					<div class="befehl-section-title">2. Auftrag</div>
					<textarea class="befehl-textarea" rows="4" placeholder="Aufgabe des Verbandes – Wer, Was, Wann, Wo, Warum…" bind:value={befehlForm.auftrag}></textarea>
				</div>

				<!-- 4. Versorgung -->
				<div class="befehl-section">
					<div class="befehl-section-title">4. Versorgung</div>
					<textarea class="befehl-textarea" rows="3" placeholder="Verpflegung, Betriebsstoff, Instandsetzung, sanitätsdienstliche Versorgung…" bind:value={befehlForm.versorgung}></textarea>
				</div>

				<!-- 6. Anlagen -->
				<div class="befehl-section">
					<div class="befehl-section-title">6. Anlagen</div>
					<textarea class="befehl-textarea" rows="2" placeholder="Beigefügte Dokumente, Karten, Skizzen…" bind:value={befehlForm.anlagen}></textarea>
				</div>
			</div>

			<div class="befehl-modal-footer">
				<button class="modal-btn-secondary" onclick={() => (showBefehlModal = false)}>Abbrechen</button>
				<button class="modal-btn-primary" onclick={async () => { await saveBefehlForm(); if (!error) showBefehlModal = false; }} disabled={befehlSaving}>
					{befehlSaved ? '✓ Gespeichert' : befehlSaving ? 'Speichert…' : 'Speichern & Schließen'}
				</button>
				<button class="modal-btn-export" onclick={async () => { await saveBefehlForm(); if (!error) downloadExport('pdf'); }} disabled={befehlSaving}>
					🖨 Speichern & PDF
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- ── Modal: Neuer Marschverband ─────────────────────────────────── -->
{#if showConvoyForm}
	<div class="modal-backdrop" onclick={() => (showConvoyForm = false)}>
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<h2>Neuer Marschverband</h2>
			<form onsubmit={(e) => { e.preventDefault(); createConvoy(); }}>
				<label>Name *<input bind:value={newConvoy.name} required placeholder="z.B. KatS-Verband Bayern 1" /></label>
				<label>Startzeit (optional)<input type="datetime-local" bind:value={newConvoy.start_time} /></label>
				<label>Geschw. innerorts (km/h)<input type="number" bind:value={newConvoy.speed_urban_kmh} min="10" max="60" /></label>
				<label>Geschw. außerorts (km/h)<input type="number" bind:value={newConvoy.speed_rural_kmh} min="30" max="100" /></label>
				<label>Straßenpräferenz
					<select bind:value={newConvoy.road_preference}>
						<option value="standard">Standard (meidet Ortschaften, gut ausgebaute Straßen)</option>
						<option value="schnell">Schnellste Route</option>
						<option value="kuerzeste">Kürzeste Route</option>
					</select>
				</label>
				<label>Fahrzeugabstand Innerorts (m)<input type="number" bind:value={newConvoy.spacing_urban_m} min="5" max="200" /></label>
				<label>Fahrzeugabstand Außerorts (m)<input type="number" bind:value={newConvoy.spacing_rural_m} min="10" max="500" /></label>
				<label>Fahrzeugabstand Autobahn (m)<input type="number" bind:value={newConvoy.spacing_motorway_m} min="10" max="500" /></label>
				<p class="hint" style="margin:.25rem 0">Weitere Felder (Lage, Auftrag, Funkgruppe…) kannst du nach dem Erstellen im Plan-Tab ergänzen.</p>
				<div class="modal-actions">
					<button type="button" onclick={() => (showConvoyForm = false)}>Abbrechen</button>
					<button type="submit" class="btn-primary">Erstellen & Punkte setzen →</button>
				</div>
			</form>
		</div>
	</div>
{/if}

{#if showShareLinkModal && selected}
	<ShareLinkModal convoyId={selected.id} onClose={() => (showShareLinkModal = false)} />
{/if}

<!-- ── Modal: Marschverband bearbeiten ──────────────────────────── -->
{#if showEditConvoyForm}
	<div class="modal-backdrop" onclick={() => (showEditConvoyForm = false)}>
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<h2>Marschverband bearbeiten</h2>
			<form onsubmit={(e) => { e.preventDefault(); saveConvoyEdit(); }}>
				<label>Name *<input bind:value={editConvoy.name} required /></label>
				<label>Organisation
					<select bind:value={editConvoy.organization_id} onchange={() => {
						const org = organizations.find(o => o.id === editConvoy.organization_id);
						editConvoy.organization = org?.name ?? '';
					}}>
						<option value="">– keine –</option>
						{#each organizations as org}
							<option value={org.id}>{org.name}</option>
						{/each}
					</select>
				</label>
				<label>Startzeit (optional)<input type="datetime-local" bind:value={editConvoy.start_time} /></label>
				<label>Geschw. innerorts (km/h)<input type="number" bind:value={editConvoy.speed_urban_kmh} min="10" max="60" /></label>
				<label>Geschw. außerorts (km/h)<input type="number" bind:value={editConvoy.speed_rural_kmh} min="30" max="100" /></label>
				<label>Straßenpräferenz
					<select bind:value={editConvoy.road_preference}>
						<option value="standard">Standard (meidet Ortschaften, gut ausgebaute Straßen)</option>
						<option value="schnell">Schnellste Route</option>
						<option value="kuerzeste">Kürzeste Route</option>
						{#if editConvoy.road_preference === 'bundesstrasse' || editConvoy.road_preference === 'landstrasse'}
							<option value={editConvoy.road_preference}>Veraltet — bitte neu wählen</option>
						{/if}
					</select>
				</label>
				<label>Fahrzeugabstand Innerorts (m)<input type="number" bind:value={editConvoy.spacing_urban_m} min="5" max="200" /></label>
				<label>Fahrzeugabstand Außerorts (m)<input type="number" bind:value={editConvoy.spacing_rural_m} min="10" max="500" /></label>
				<label>Fahrzeugabstand Autobahn (m)<input type="number" bind:value={editConvoy.spacing_motorway_m} min="10" max="500" /></label>
				<div class="modal-actions">
					<button type="button" class="btn-danger" onclick={deleteConvoy}>Löschen</button>
					<button type="button" onclick={() => (showEditConvoyForm = false)}>Abbrechen</button>
					<button type="submit" class="btn-primary">Speichern</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }
	/* 100dvh follows the iOS Safari URL bar so content (FAB, sidebar footer) stays reachable.
	   100vh kept as a fallback for browsers without dvh support. */
	.app { display: flex; height: 100vh; height: 100dvh; overflow: hidden; }

	.sidebar { width: 340px; min-width: 280px; background: var(--sidebar-bg); color: var(--text-1); display: flex; flex-direction: column; overflow: hidden; }
	.sidebar-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid var(--border); background: var(--sidebar-bg); }
	.logo-wrap { flex: 1; min-width: 0; }
.logout-btn { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1rem; flex-shrink: 0; }
.admin-link { font-size: var(--text-xs); color: var(--text-muted); text-decoration: none; white-space: nowrap; }
.admin-link:hover { color: var(--text-2); }

	.convoy-selector { display: flex; gap: .5rem; padding: .75rem 1rem; border-bottom: 1px solid var(--border); }
.convoy-selector select { flex: 1; padding: .5rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }

	.tabs { display: flex; overflow-x: auto; scrollbar-width: none; padding: .25rem .5rem; gap: .25rem; border-bottom: 1px solid var(--border); }
.tabs::-webkit-scrollbar { display: none; }
.tab { flex: 0 0 auto; padding: .5rem .75rem; background: none; border: none; color: var(--text-2); font-size: var(--text-sm); cursor: pointer; white-space: nowrap; border-radius: 4px; }
.tab.active { color: var(--text-1); background: var(--surface-2); font-weight: 600; }
.tabs-verwaltung { padding: .25rem .5rem; gap: .25rem; border-bottom: 1px solid var(--border); }
.tabs-verwaltung .tab { font-size: var(--text-sm); }
.tabs-verwaltung .tab.active { color: var(--text-1); background: var(--surface-2); }
.tabs-section-label { flex-shrink: 0; font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); padding: 0 .5rem; white-space: nowrap; align-self: center; }

	.tab-content { flex: 1; overflow-y: auto; padding: .75rem 1rem; }

.section { margin-bottom: .75rem; }
.section p { margin: .25rem 0; font-size: var(--text-sm); color: var(--text-2); }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-top: 1.5rem; margin-bottom: .5rem; font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }

	.map-actions { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: .5rem; }
.btn-map { padding: .25rem .5rem; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-2); border-radius: 4px; font-size: var(--text-xs); cursor: pointer; }
	.btn-map.active { background: var(--color-primary); border-color: var(--color-primary); }

	.btn-primary { width: 100%; padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }

	.btn-small { padding: .25rem .5rem; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-2); border-radius: 4px; font-size: var(--text-xs); cursor: pointer; }
	.btn-small.danger { background: rgba(226,61,40,.3); border-color: var(--color-primary); }
	.btn-small.active { background: var(--color-primary); }

	.export-grid { display: flex; flex-direction: column; gap: .4rem; margin-top: .4rem; }
	/* Marschbefehl Modal */
	.befehl-backdrop { align-items: flex-start; padding: 2rem 1rem; overflow-y: auto; }
	.befehl-modal { background: white; color: #1a1a1a; border-radius: 10px; width: 100%; max-width: 720px; margin: auto; display: flex; flex-direction: column; max-height: 90vh; box-shadow: 0 12px 48px rgba(0,0,0,.45); }
	.befehl-modal-header { display: flex; align-items: center; gap: .75rem; padding: 1.25rem 1.5rem; border-bottom: 2px solid #0F1B24; background: #0F1B24; border-radius: 10px 10px 0 0; flex-shrink: 0; }
	.befehl-modal-header h2 { margin: 0; font-size: 1.15rem; color: white; }
	.befehl-convoy-name { flex: 1; font-size: .85rem; color: rgba(255,255,255,.55); }
	.modal-close { background: none; border: none; color: rgba(255,255,255,.55); cursor: pointer; font-size: 1.1rem; padding: 0; line-height: 1; }
	.modal-close:hover { color: white; }
	.befehl-modal-body { flex: 1; overflow-y: auto; padding: 1.5rem; display: flex; flex-direction: column; gap: 1.4rem; }
	.befehl-section { display: flex; flex-direction: column; gap: .6rem; }
	.befehl-section-title { font-size: .7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .09em; color: #0F1B24; border-bottom: 2px solid #0F1B24; padding-bottom: .3rem; }
	.befehl-row { display: flex; gap: .75rem; flex-wrap: wrap; }
	.befehl-row-3 > * { flex: 1; min-width: 140px; }
	.befehl-row > * { flex: 1; }
	.bf-label { display: flex; flex-direction: column; gap: .3rem; font-size: .8rem; font-weight: 600; color: #333; }
	.bf-label input, .bf-label select { padding: .5rem .65rem; border-radius: 5px; border: 1.5px solid #ccc; background: white; color: #111; font-size: .9rem; font-family: inherit; }
	.bf-label input:focus, .bf-label select:focus { outline: none; border-color: var(--color-primary); box-shadow: 0 0 0 3px rgba(226,61,40,.12); }
	.bf-label input::placeholder { color: #aaa; }
	.befehl-textarea { padding: .55rem .7rem; border-radius: 5px; border: 1.5px solid #ccc; background: white; color: #111; font-size: .9rem; font-family: inherit; resize: vertical; width: 100%; box-sizing: border-box; line-height: 1.5; }
	.befehl-textarea:focus { outline: none; border-color: var(--color-primary); box-shadow: 0 0 0 3px rgba(226,61,40,.12); }
	.befehl-textarea::placeholder { color: #aaa; }
	.befehl-modal-footer { display: flex; justify-content: flex-end; gap: .6rem; padding: 1rem 1.5rem; border-top: 1px solid #e5e5e5; flex-shrink: 0; flex-wrap: wrap; background: #f8f9fa; border-radius: 0 0 10px 10px; }
	.modal-btn-secondary { padding: .55rem 1.1rem; border-radius: 5px; border: 1.5px solid #ccc; background: white; color: #555; cursor: pointer; font-size: .88rem; }
	.modal-btn-secondary:hover { background: #f0f0f0; }
	.modal-btn-primary { padding: .55rem 1.1rem; border-radius: 5px; border: none; background: #0F1B24; color: white; cursor: pointer; font-size: .88rem; font-weight: 600; }
	.modal-btn-primary:hover { background: #1a2f42; }
	.modal-btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.modal-btn-export { padding: .55rem 1.1rem; border-radius: 5px; border: none; background: var(--color-primary); color: white; cursor: pointer; font-size: .88rem; font-weight: 600; }
	.modal-btn-export:hover { background: var(--color-primary-hover); }
	.modal-btn-export:disabled { opacity: .5; cursor: not-allowed; }
	.btn-export { display: block; padding: .45rem .75rem; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-2); border-radius: 4px; font-size: var(--text-sm); text-decoration: none; cursor: pointer; text-align: left; }
	.btn-export.active { background: rgba(226,61,40,.3); border-color: var(--color-primary); }

	.route-actions { margin-top: .75rem; }
	.route-info { font-size: var(--text-sm); color: var(--text-2); margin: .4rem 0; }

	.hint { font-size: var(--text-xs); color: var(--text-muted); font-style: italic; margin: .25rem 0; }

	.vehicle-list { list-style: none; padding: 0; margin: 0; }
	.vehicle-item { display: flex; justify-content: space-between; align-items: center; padding: .35rem 0; border-bottom: 1px solid var(--border); font-size: var(--text-sm); }
	.status-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }

	.tag { display: inline-block; padding: .1rem .3rem; background: var(--surface-2); border-radius: 3px; font-size: var(--text-xs); margin-left: .2rem; }
	.tag.orange { background: rgba(230,126,34,.4); }

	.wp-list { list-style: none; padding: 0; margin: 0; }
	.wp-item { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; padding: .35rem 0; border-bottom: 1px solid var(--border); font-size: var(--text-sm); cursor: grab; }
	.wp-main { flex: 1; }
	.wp-actions { display: flex; gap: .25rem; }
	.wp-edit-form {
  width: 100%;
  display: flex; flex-direction: column; gap: .3rem;
  padding: .4rem .5rem;
  background: var(--surface-1);
  border-radius: 4px;
  margin-bottom: .25rem;
}
	.wp-edit-form input, .wp-edit-form select {
  padding: .3rem .4rem; border: 1px solid var(--border); border-radius: 3px;
  background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm);
}
	.wp-edit-actions { display: flex; gap: .3rem; }

	.wp-quick-form { background: var(--surface-1); border-radius: 4px; padding: .5rem; margin-bottom: .5rem; display: flex; flex-direction: column; gap: .35rem; }
	.wp-quick-form input, .wp-quick-form select { padding: .3rem .4rem; border: 1px solid var(--border); border-radius: 3px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }

	.schedule-table { width: 100%; border-collapse: collapse; font-size: .8rem; }
	.schedule-table th, .schedule-table td { padding: .3rem .4rem; text-align: left; border-bottom: 1px solid var(--border); color: var(--text-1); }
	.schedule-table th { color: var(--text-muted); font-weight: 600; }

	.inline-form { display: flex; flex-direction: column; gap: .35rem; margin-bottom: .5rem; }
	.inline-form input, .inline-form select { padding: .35rem .4rem; border-radius: 4px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
	.inline-form input::placeholder { color: var(--text-muted); }
	.inline-form button { padding: .35rem; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer; }

	.sub-convoy-item { padding: .3rem .4rem; background: var(--surface-1); border-radius: 4px; margin-bottom: .25rem; font-size: var(--text-sm); cursor: pointer; }
	.sub-convoy-item:hover { background: var(--surface-2); }

	.org-item { display: flex; justify-content: space-between; align-items: center; padding: .35rem 0; border-bottom: 1px solid var(--border); font-size: var(--text-sm); }

	.tag-pill { display: inline-block; background: rgba(52,152,219,.3); border: 1px solid var(--color-accent); border-radius: 12px; padding: .1rem .5rem; font-size: .72rem; color: #74b9ff; }

	.error-bar { background: var(--color-primary-hover); color: white; padding: .4rem .75rem; font-size: .8rem; margin: 0; display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; flex-shrink: 0; word-break: break-word; }
	.error-bar button { background: none; border: none; color: white; cursor: pointer; font-size: 1rem; flex-shrink: 0; line-height: 1; padding: 0; }
	.success-bar { background: rgba(39,174,96,.25); color: #a9dfbf; padding: .4rem .75rem; font-size: .8rem; margin: 0 0 .5rem 0; border-radius: 4px; }

	.map-area { flex: 1; position: relative; }
	/* Desktop defaults — these elements exist in DOM but are hidden */
	.topbar { display: none; }
	.sidebar-backdrop { display: none; }
	.fab-route { display: none; }
	.map-hint-bar { position: absolute; top: 1rem; left: 50%; transform: translateX(-50%); z-index: 10; background: rgba(15,27,36,.9); color: white; padding: .5rem 1rem; border-radius: 20px; display: flex; align-items: center; gap: 1rem; font-size: .85rem; }
	.map-hint-bar button { background: rgba(255,255,255,.2); border: none; color: white; border-radius: 12px; padding: .2rem .6rem; cursor: pointer; }

	/* Modal */
	.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
	.modal { background: white; border-radius: 8px; padding: 2rem; width: 100%; max-width: 420px; color: #333; }
	.modal h2 { margin: 0 0 1.25rem; }
	.modal label { display: flex; flex-direction: column; gap: .25rem; margin-bottom: .75rem; font-size: .85rem; font-weight: 600; }
	.modal input, .modal select { padding: .5rem; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; }
	.modal-actions { display: flex; justify-content: flex-end; gap: .5rem; margin-top: 1rem; flex-wrap: wrap; }
	.modal-actions .btn-danger { background: #b91c1c; color: white; border-color: #b91c1c; margin-right: auto; }
	.modal-actions .btn-danger:hover { background: #991b1b; }
	.modal-actions button { padding: .5rem 1rem; border-radius: 4px; cursor: pointer; border: 1px solid #ccc; }
	.modal-actions .btn-primary { background: #0F1B24; color: white; border-color: #0F1B24; }
	.modal { max-height: 90vh; overflow-y: auto; }
	.modal label textarea { padding: .5rem; border: 1px solid #ccc; border-radius: 4px; font-size: .9rem; resize: vertical; }
	.modal label small { font-weight: 400; color: #888; font-size: .78rem; }

	.convoy-vehicle-row { flex-direction: row; gap: .4rem; }
	.veh-left { display: flex; align-items: center; gap: .35rem; flex: 1; min-width: 0; }
	.veh-pos { font-size: var(--text-xs); color: var(--text-muted); flex-shrink: 0; }
	.tag.sonder { background: rgba(52,152,219,.4); color: #aed6f1; }

	.sf-select { width: 100%; padding: .25rem .35rem; border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); font-size: var(--text-xs); }

	.detail-text { font-size: var(--text-sm); color: var(--text-2); margin: .25rem 0 0; white-space: pre-wrap; }
	details summary { cursor: pointer; font-size: var(--text-sm); color: var(--text-2); }

	.tag.fuel-tag { background: rgba(39,174,96,.35); color: #a9dfbf; }
	.tag.fuel-tag-default { background: rgba(180,150,30,.25); color: #d4b96a; }

	.fuel-warning { background: rgba(226,61,40,.15); border: 1px solid rgba(226,61,40,.5); border-radius: 6px; padding: .65rem; margin-top: .5rem; display: flex; flex-direction: column; gap: .3rem; }
	.fuel-warning p { margin: 0; font-size: .83rem; }
	.fuel-rec-title { font-weight: 700; font-size: .88rem; color: #f0a070; }
	.fuel-detail { color: rgba(255,255,255,.85); }
	.fuel-defaults-note { color: rgba(255,255,255,.55); font-size: .78rem; font-style: italic; border-top: 1px solid rgba(255,255,255,.1); padding-top: .3rem; margin-top: .1rem; }
	.fuel-actions { margin-top: .2rem; }
	.btn-fuel-search { width: 100%; padding: .4rem; background: #e67e22; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: .82rem; font-weight: 600; }
	.btn-fuel-search:disabled { opacity: .5; cursor: not-allowed; }
	.fuel-defaults-inline { color: rgba(255,255,255,.45); font-size: .78rem; }

	.fuel-station-list { list-style: none; padding: 0; margin: .4rem 0 0; display: flex; flex-direction: column; gap: .3rem; }
	.fuel-station-item { display: flex; justify-content: space-between; align-items: flex-start; gap: .4rem; padding: .35rem; background: rgba(255,255,255,.07); border-radius: 4px; font-size: .8rem; }

	.fuel-ok { font-size: .8rem; color: #a9dfbf; margin: .3rem 0 0; }

	.th-warning { background: rgba(52,152,219,.12); border: 1px solid rgba(52,152,219,.4); border-radius: 6px; padding: .65rem; margin-top: .5rem; display: flex; flex-direction: column; gap: .3rem; }
	.th-warning p { margin: 0; font-size: .83rem; }
	.th-title { font-weight: 700; font-size: .88rem; color: #7fbde8; }
	.th-detail { color: rgba(255,255,255,.8); }
	.th-list { list-style: none; padding: 0; margin: .2rem 0 0; display: flex; flex-direction: column; gap: .3rem; }
	.th-item { display: flex; justify-content: space-between; align-items: center; gap: .4rem; padding: .35rem; background: rgba(255,255,255,.06); border-radius: 4px; font-size: .82rem; }
	.tag.th-tag { background: rgba(52,152,219,.25); color: #7fbde8; }
	.tag.th-rest-tag { background: rgba(155,89,182,.25); color: #c39bd3; }

	.wizard { flex: 1; overflow-y: auto; padding: .75rem 1rem; display: flex; flex-direction: column; gap: .5rem; }
	.wizard-steps { display: flex; align-items: center; gap: .3rem; font-size: .75rem; color: rgba(255,255,255,.4); margin-bottom: .25rem; }
	.wizard-steps span.active { color: white; font-weight: 700; }
	.wizard-steps .sep { color: rgba(255,255,255,.25); }
	.wizard-title { margin: 0 0 .5rem; font-size: .95rem; font-weight: 600; color: white; }
	.btn-skip { background: none; border: none; color: var(--text-muted); font-size: .78rem; cursor: pointer; padding: .2rem 0; text-align: left; }
	.btn-skip:hover { color: var(--text-2); }
	.wp-name-input { width: 100%; padding: .4rem .6rem; border-radius: 4px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: .85rem; box-sizing: border-box; }
	.wp-name-input::placeholder { color: var(--text-muted); }
	.wizard-wp-list { list-style: none; padding: 0; margin: 0; max-height: 120px; overflow-y: auto; }
	.wizard-wp-list li { font-size: .8rem; color: var(--text-2); padding: .2rem 0; border-bottom: 1px solid var(--border); }

	/* ── Org management ─────────────────────────────────────────── */
	.org-card { background: rgba(255,255,255,.05); border-radius: 8px; margin-bottom: .5rem; overflow: hidden; }
	.org-header { display: flex; justify-content: space-between; align-items: center; padding: .55rem .75rem; cursor: pointer; user-select: none; }
	.org-header:hover { background: rgba(255,255,255,.05); }
	.org-header span { font-size: .85rem; font-weight: 600; color: white; }
	.org-header small { font-size: .72rem; color: rgba(255,255,255,.45); }
	.org-header .expand-icon { font-size: .7rem; color: rgba(255,255,255,.4); }
	.org-detail { padding: .5rem .75rem .75rem; border-top: 1px solid rgba(255,255,255,.08); }
	.org-section-label { margin: 0 0 .35rem; font-size: .72rem; text-transform: uppercase; letter-spacing: .04em; color: rgba(255,255,255,.4); }
	.org-convoy-row { display: flex; align-items: center; justify-content: space-between; padding: .25rem 0; font-size: .8rem; color: rgba(255,255,255,.75); border-bottom: 1px solid rgba(255,255,255,.06); }
	.org-convoy-row:last-child { border-bottom: none; }
	.org-member-row { display: flex; align-items: center; gap: .5rem; padding: .25rem 0; border-bottom: 1px solid rgba(255,255,255,.06); }
	.org-member-row:last-child { border-bottom: none; }
	.org-member-email { flex: 1; font-size: .8rem; color: rgba(255,255,255,.8); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.org-role-select { background: var(--surface-2); border: 1px solid var(--border); color: var(--text-1); border-radius: 4px; padding: .2rem .4rem; font-size: .75rem; cursor: pointer; }
	.org-add-member { display: flex; gap: .4rem; margin-top: .6rem; flex-wrap: wrap; }
	.org-email-input { flex: 1; min-width: 120px; padding: .3rem .5rem; border-radius: 4px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: .8rem; }
	.org-email-input::placeholder { color: var(--text-muted); }
	.invite-form { display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .3rem; }
	.invite-form input { flex: 1; min-width: 120px; padding: .3rem .5rem; border-radius: 4px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: .8rem; }

	/* ── Mobile layout (≤ 768px) ─────────────────────────────────── */
	@media (max-width: 768px) {
		/* Show top bar, push content down */
		.topbar {
			display: flex;
			align-items: center;
			gap: .5rem;
			position: fixed;
			top: 0; left: 0; right: 0;
			height: calc(52px + env(safe-area-inset-top));
			padding-top: env(safe-area-inset-top);
			padding-left: max(.75rem, env(safe-area-inset-left));
			padding-right: max(.75rem, env(safe-area-inset-right));
			background: var(--sidebar-bg);
			border-bottom: 1px solid var(--border);
			/* Above sidebar (300) and backdrop (299) so the hamburger stays
			   visible and tappable while the sidebar is open. */
			z-index: 301;
			overflow: hidden;
		}

		/* Hide floating map overlays when the sidebar is open — they would
		   otherwise sit on top of the sidebar (InfoPill) or look stranded
		   along the visible edge of the map (route FAB). */
		.app.sidebar-open :global(.pill-wrap),
		.app.sidebar-open .fab-route,
		.app.sidebar-open .map-hint-bar {
			display: none;
		}
		.hamburger {
			background: rgba(255,255,255,.1);
			border: none;
			color: white;
			border-radius: 8px;
			width: 40px;
			height: 40px;
			font-size: 1.2rem;
			cursor: pointer;
			flex-shrink: 0;
			display: flex;
			align-items: center;
			justify-content: center;
		}
		.topbar-name {
			flex: 1;
			/* min-width: 0 lets the flex item actually shrink past its text width;
			   without it, a long convoy name would push the action buttons offscreen. */
			min-width: 0;
			font-size: .9rem;
			font-weight: 600;
			color: white;
			white-space: nowrap;
			overflow: hidden;
			text-overflow: ellipsis;
		}
		.topbar-actions {
			display: flex;
			gap: .25rem;
			flex-shrink: 0;
		}
		.topbar-actions .btn-map {
			min-width: 40px;
			height: 40px;
			padding: 0 .5rem;
			font-size: .9rem;
			display: flex;
			align-items: center;
			justify-content: center;
		}

		/* Push the flex layout down to clear the fixed top bar (incl. notch). */
		.app {
			padding-top: calc(52px + env(safe-area-inset-top));
			box-sizing: border-box;
		}

		/* Sidebar becomes a fixed overlay from the left.
		   height uses dvh so the iOS Safari URL bar doesn't hide the bottom of
		   the panel — otherwise the route button & theme/version footer would
		   sit behind the address bar. */
		.sidebar {
			position: fixed;
			top: calc(52px + env(safe-area-inset-top));
			left: 0;
			bottom: auto;
			height: calc(100dvh - 52px - env(safe-area-inset-top));
			/* Cap to viewport so 88vw never produces a sub-pixel scrollbar on narrow screens. */
			width: min(320px, 88vw);
			min-width: 0;
			max-width: 100vw;
			z-index: 300;
			overflow-y: hidden;
			padding-bottom: env(safe-area-inset-bottom);
			padding-left: env(safe-area-inset-left);
			transform: translateX(-100%);
			transition: transform .25s ease;
		}
		.sidebar.open {
			transform: translateX(0);
		}

		/* Backdrop behind open sidebar */
		.sidebar-backdrop {
			display: block;
			position: fixed;
			inset: 0;
			background: rgba(0,0,0,.45);
			z-index: 299;
		}

		/* FAB route button floating over map. Sits above the iOS home indicator
		   and respects the URL bar via dvh on .app. */
		.fab-route {
			display: flex;
			align-items: center;
			gap: .4rem;
			position: fixed;
			bottom: calc(1.5rem + env(safe-area-inset-bottom));
			right: calc(1rem + env(safe-area-inset-right));
			z-index: 50;
			padding: .7rem 1.25rem;
			background: var(--color-primary);
			color: white;
			border: none;
			border-radius: 10px;
			font-size: .95rem;
			font-weight: 600;
			cursor: pointer;
			box-shadow: 0 4px 16px rgba(0,0,0,.35);
			min-height: 44px;
		}
		.fab-route:disabled {
			opacity: .55;
			cursor: not-allowed;
		}

		/* Modal: edge-to-edge with safe insets */
		.modal {
			max-width: calc(100vw - 2rem);
			padding: 1.25rem;
			margin: .75rem;
		}
	}

	.kw-section { margin-top: .75rem; }
	.kw-table td code { background: var(--surface-2); color: var(--text-1); padding: .1rem .3rem; border-radius: 3px; font-size: .8rem; }
	.kw-befehl-table { width: 100%; border-collapse: collapse; font-size: .82rem; margin-top: .3rem; }
	.kw-befehl-table th, .kw-befehl-table td { padding: .3rem .5rem; border: 1px solid var(--border); text-align: left; color: var(--text-1); }
	.kw-befehl-table th { background: var(--surface-2); color: var(--text-muted); }
	.kw-befehl-table td code { background: var(--surface-2); color: var(--text-1); padding: .1rem .3rem; border-radius: 3px; }

	.sidebar-footer { flex-shrink: 0; border-top: 1px solid var(--border); padding: .75rem 1rem; display: flex; align-items: center; justify-content: space-between; }
	.theme-toggle { display: flex; align-items: center; gap: .4rem; background: none; border: 1px solid var(--border); border-radius: 6px; color: var(--text-2); font-size: var(--text-sm); padding: .25rem .5rem; cursor: pointer; }
	.theme-toggle:hover { background: var(--surface-2); }
	.app-version { font-size: var(--text-xs); color: var(--text-muted); }
	.app-version .update-hint { color: #f59e0b; font-weight: 600; text-decoration: none; }
	.app-version .update-hint:hover { text-decoration: underline; }
</style>
