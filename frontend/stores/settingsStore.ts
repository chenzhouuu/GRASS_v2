"use client";

import { create } from "zustand";
import type { AgentName } from "@/lib/types";
import { useAppStore } from "@/stores/appStore";
import { MapConfigValidator } from "@/lib/validators";
import {
  fetchSessionModelConfig,
  updateSessionModelConfig,
  type ModelConfig,
  type ProviderApiKeys,
  type RuntimeApiKeyProvider,
} from "@/lib/model-config";

// ── Types ────────────────────────────────────────────────────────────────────

export type Theme = "light" | "dark" | "system";
export type ExportFormat = "pdf" | "csv" | "json";

export interface DatabaseConfig {
  uri: string;
  username: string;
  password: string;
  database: string;
}

export interface MapConfig {
  center: [number, number];
  zoom: number;
  tileProvider: "osm" | "carto-light" | "carto-dark";
}

const MODEL_CAPABLE_AGENTS: AgentName[] = [
  "Supervisor",
  "Cypher",
  "Analytics",
  "Optimization",
  "Report",
];

export { MODEL_CAPABLE_AGENTS };

// ── Defaults ─────────────────────────────────────────────────────────────────

const DEFAULT_API_KEYS: ProviderApiKeys = {
  openai: "",
  anthropic: "",
  google: "",
};

const DEFAULT_MODELS: Partial<Record<AgentName, ModelConfig>> = {
  Supervisor: { provider: "openai", model: "gpt-5.4-mini" },
  Cypher: { provider: "openai", model: "gpt-5.4-mini" },
  Analytics: { provider: "openai", model: "gpt-5.4-mini" },
  Optimization: { provider: "openai", model: "gpt-5.4-mini" },
  Report: { provider: "openai", model: "gpt-5.4-mini" },
};

const DEFAULT_DB: DatabaseConfig = {
  uri: "bolt://localhost:7687",
  username: "neo4j",
  password: "",
  database: "neo4j",
};

const DEFAULT_MAP: MapConfig = {
  center: [39.8283, -98.5795], // center of US
  zoom: 5,
  tileProvider: "osm",
};

// ── Versioning & Migration ───────────────────────────────────────────────────
// Inspired by NextChat createPersistStore (app/store/config.ts:196-261)

const SETTINGS_VERSION = 2;

interface PersistedSettings {
  _version?: number;
  theme?: Theme;
  exportFormat?: ExportFormat;
  agentModels?: Partial<Record<AgentName, ModelConfig>>;
  providerApiKeys?: Partial<ProviderApiKeys>;
  database?: Partial<DatabaseConfig>;
  map?: Partial<MapConfig>;
}

function migrateSettings(persisted: PersistedSettings): PersistedSettings {
  const version = persisted._version ?? 0;
  const migrated: PersistedSettings = {
    ...persisted,
    agentModels: persisted.agentModels ? { ...persisted.agentModels } : undefined,
    providerApiKeys: persisted.providerApiKeys
      ? { ...persisted.providerApiKeys }
      : undefined,
    database: persisted.database ? { ...persisted.database } : undefined,
    map: persisted.map ? { ...persisted.map } : undefined,
  };

  if (version < 1 && migrated.agentModels) {
    for (const [agent, config] of Object.entries(DEFAULT_MODELS)) {
      if (!migrated.agentModels[agent as AgentName]) {
        migrated.agentModels[agent as AgentName] = { ...config };
      }
    }
  }

  if (version < 2) {
    migrated.providerApiKeys = normalizeProviderApiKeys(
      persisted.providerApiKeys,
    );
  }

  if (migrated.database) {
    migrated.database = { ...DEFAULT_DB, ...migrated.database };
  }

  if (migrated.map) {
    migrated.map = normalizeMapConfig(migrated.map);
  }

  migrated._version = SETTINGS_VERSION;
  return migrated;
}

// ── Storage helpers ──────────────────────────────────────────────────────────

const STORAGE_KEY = "grass-settings";

/**
 * Merge persisted partial settings with current defaults.
 * Ensures new default fields appear in existing users' settings.
 * Inspired by NextChat config.ts:200-212 merge function.
 */
function mergeWithDefaults<T extends Record<string, unknown>>(
  persisted: Partial<T> | undefined,
  defaults: T,
): T {
  if (!persisted) return { ...defaults };
  return { ...defaults, ...persisted };
}

function cloneCenter(center: [number, number]): [number, number] {
  return [center[0], center[1]];
}

function isMapTileProvider(value: unknown): value is MapConfig["tileProvider"] {
  return value === "osm" || value === "carto-light" || value === "carto-dark";
}

function normalizeProviderApiKeys(
  persisted?: Partial<ProviderApiKeys>,
): ProviderApiKeys {
  return { ...DEFAULT_API_KEYS, ...persisted };
}

function normalizeMapConfig(persisted?: Partial<MapConfig>): MapConfig {
  if (!persisted) {
    return {
      ...DEFAULT_MAP,
      center: cloneCenter(DEFAULT_MAP.center),
    };
  }

  const center = Array.isArray(persisted.center) && persisted.center.length === 2
    ? [
        MapConfigValidator.latitude(Number(persisted.center[0])),
        MapConfigValidator.longitude(Number(persisted.center[1])),
      ] as [number, number]
    : cloneCenter(DEFAULT_MAP.center);

  return {
    center,
    zoom: MapConfigValidator.zoom(Number(persisted.zoom)),
    tileProvider: isMapTileProvider(persisted.tileProvider)
      ? persisted.tileProvider
      : DEFAULT_MAP.tileProvider,
  };
}

function loadSettings(): Partial<PersistedSettings> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as PersistedSettings;
    const migrated = migrateSettings(parsed);
    if (raw !== JSON.stringify(migrated)) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated));
    }
    return migrated;
  } catch {
    return {};
  }
}

function saveSettings(state: SettingsState) {
  if (typeof window === "undefined") return;
  try {
    const {
      theme,
      exportFormat,
      agentModels,
      providerApiKeys,
      database,
      map,
    } = state;
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        _version: SETTINGS_VERSION,
        theme,
        exportFormat,
        agentModels,
        providerApiKeys,
        database,
        map,
      }),
    );
  } catch {
    // silently fail
  }
}

function cloneDefaultModels(): Partial<Record<AgentName, ModelConfig>> {
  return Object.fromEntries(
    Object.entries(DEFAULT_MODELS).map(([agent, config]) => [
      agent,
      { ...config },
    ]),
  ) as Partial<Record<AgentName, ModelConfig>>;
}

function cloneDefaultApiKeys(): ProviderApiKeys {
  return { ...DEFAULT_API_KEYS };
}

// ── Store ────────────────────────────────────────────────────────────────────

interface SettingsState {
  // General
  theme: Theme;
  exportFormat: ExportFormat;
  setTheme: (theme: Theme) => void;
  setExportFormat: (format: ExportFormat) => void;

  // Models
  agentModels: Partial<Record<AgentName, ModelConfig>>;
  modelConfigDirty: boolean;
  setAgentModel: (agent: AgentName, config: ModelConfig) => void;
  providerApiKeys: ProviderApiKeys;
  setProviderApiKey: (provider: RuntimeApiKeyProvider, value: string) => void;
  applySessionModelConfig: (
    agentModels: Partial<Record<AgentName, ModelConfig>>,
    providerApiKeys: ProviderApiKeys,
    markDirty?: boolean,
  ) => void;
  loadSessionModelConfig: (sessionId: string) => Promise<void>;
  saveSessionModelConfig: (sessionId: string) => Promise<void>;
  resetSessionModelConfig: () => void;
  hasNonDefaultModelConfig: () => boolean;

  // Database
  database: DatabaseConfig;
  setDatabase: (patch: Partial<DatabaseConfig>) => void;

  // Map
  map: MapConfig;
  setMapConfig: (patch: Partial<MapConfig>) => void;

  // Dialog
  isOpen: boolean;
  setOpen: (open: boolean) => void;
}

const saved = loadSettings();

export const useSettingsStore = create<SettingsState>((set) => ({
  // General
  theme: saved.theme ?? "system",
  exportFormat: saved.exportFormat ?? "pdf",
  setTheme: (theme) =>
    set((s) => {
      const next = { ...s, theme };
      saveSettings(next);
      return { theme };
    }),
  setExportFormat: (exportFormat) =>
    set((s) => {
      const next = { ...s, exportFormat };
      saveSettings(next);
      return { exportFormat };
    }),

  // Models — mergeWithDefaults ensures new agents appear in existing settings
  agentModels: mergeWithDefaults(saved.agentModels, cloneDefaultModels()),
  modelConfigDirty: false,
  setAgentModel: (agent, config) =>
    set((s) => {
      const agentModels = { ...s.agentModels, [agent]: config };
      const next = { ...s, agentModels };
      saveSettings(next);
      return { agentModels, modelConfigDirty: true };
    }),
  providerApiKeys: normalizeProviderApiKeys(saved.providerApiKeys),
  setProviderApiKey: (provider, value) =>
    set((s) => {
      const providerApiKeys = {
        ...s.providerApiKeys,
        [provider]: value,
      };
      const next = {
        ...s,
        providerApiKeys,
      };
      saveSettings(next);
      return { providerApiKeys, modelConfigDirty: true };
    }),
  applySessionModelConfig: (agentModels, providerApiKeys, markDirty = false) =>
    set((s) => {
      const next = {
        ...s,
        agentModels: mergeWithDefaults(agentModels, cloneDefaultModels()),
        providerApiKeys: normalizeProviderApiKeys(providerApiKeys),
      };
      saveSettings(next);
      return {
        agentModels: next.agentModels,
        providerApiKeys: next.providerApiKeys,
        modelConfigDirty: markDirty,
      };
    }),
  loadSessionModelConfig: async (sessionId) => {
    const config = await fetchSessionModelConfig(sessionId);
    if (useAppStore.getState().currentSessionId !== sessionId) return;
    useSettingsStore.getState().applySessionModelConfig(
      config.agent_models,
      config.api_keys,
      false,
    );
  },
  saveSessionModelConfig: async (sessionId) => {
    const state = useSettingsStore.getState();
    if (!state.modelConfigDirty) return;
    const config = await updateSessionModelConfig(sessionId, {
      agent_models: state.agentModels,
      api_keys: state.providerApiKeys,
    });
    useSettingsStore.getState().applySessionModelConfig(
      config.agent_models,
      config.api_keys,
      false,
    );
  },
  resetSessionModelConfig: () =>
    set((s) => {
      const agentModels = cloneDefaultModels();
      const providerApiKeys = cloneDefaultApiKeys();
      saveSettings({ ...s, agentModels, providerApiKeys });
      return { agentModels, providerApiKeys, modelConfigDirty: false };
    }),
  hasNonDefaultModelConfig: (): boolean => {
    const { agentModels, providerApiKeys } = useSettingsStore.getState();
    const defaultModels = cloneDefaultModels();
    const modelsMatch = JSON.stringify(agentModels) === JSON.stringify(defaultModels);
    const keysMatch = Object.values(providerApiKeys).every((v) => !v);
    return !modelsMatch || !keysMatch;
  },

  // Database — mergeWithDefaults handles partial persisted configs
  database: mergeWithDefaults(saved.database, { ...DEFAULT_DB }),
  setDatabase: (patch) =>
    set((s) => {
      const database = { ...s.database, ...patch };
      const next = { ...s, database };
      saveSettings(next);
      return { database };
    }),

  // Map
  map: normalizeMapConfig(saved.map),
  setMapConfig: (patch) =>
    set((s) => {
      const map = normalizeMapConfig({ ...s.map, ...patch });
      const next = { ...s, map };
      saveSettings(next);
      return { map };
    }),

  // Dialog
  isOpen: false,
  setOpen: (isOpen) => set({ isOpen }),
}));

export function getDefaultMapViewport() {
  const { center, zoom } = useSettingsStore.getState().map;
  return {
    center: cloneCenter(center),
    zoom,
  };
}
