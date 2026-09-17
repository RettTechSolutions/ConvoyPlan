import { loadInfoPage } from '$lib/server/agent/page-load';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ url, fetch }) => loadInfoPage('terms', url, fetch);
