import { writable } from 'svelte/store';
import { authApi } from '$lib/api';

function createAuthStore() {
	const { subscribe, set } = writable<{ token: string | null }>({ token: null });

	const init = () => {
		const token = localStorage.getItem('token');
		set({ token });
	};

	const login = async (email: string, password: string) => {
		const data = await authApi.login(email, password);
		localStorage.setItem('token', data.access_token);
		set({ token: data.access_token });
	};

	const logout = () => {
		localStorage.removeItem('token');
		set({ token: null });
	};

	return { subscribe, init, login, logout };
}

export const auth = createAuthStore();
export const isLoggedIn = { subscribe: (fn: (v: boolean) => void) => auth.subscribe((s) => fn(!!s.token)) };
