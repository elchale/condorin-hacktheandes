// Route chunks. Each loader is also used to prefetch on hover.
export const loadEntrar = () => import("./pages/Entrar");
export const loadAcerca = () => import("./pages/Acerca");
export const loadPanel = () => import("./features/panel/PanelPage");
export const loadEvento = () => import("./features/evento/EventoPage");
export const loadExpediente = () => import("./features/expediente/ExpedientePage");
export const loadPrivacidad = () => import("./features/legal/PrivacidadPage");
export const loadTerminos = () => import("./features/legal/TerminosPage");
