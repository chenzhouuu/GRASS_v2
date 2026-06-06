"use client";

import { useState, useCallback, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useSettingsStore } from "@/stores/settingsStore";
import { useAppStore } from "@/stores/appStore";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Eye,
  EyeOff,
  Circle,
} from "lucide-react";
import { updateNeo4jConfig } from "@/lib/neo4j";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

type ConnectionStatus = "idle" | "testing" | "success" | "error";

function FormField({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium">
        {label}
      </label>
      {children}
    </div>
  );
}

export function DatabaseTab() {
  const database = useSettingsStore((s) => s.database);
  const setDatabase = useSettingsStore((s) => s.setDatabase);
  const neo4jConnected = useAppStore((s) => s.neo4jConnected);
  const setNeo4jConnected = useAppStore((s) => s.setNeo4jConnected);
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    setStatus(neo4jConnected ? "success" : "idle");
  }, [neo4jConnected]);

  const testConnection = useCallback(async () => {
    setStatus("testing");
    setErrorMsg("");
    try {
      const config = await updateNeo4jConfig(database);
      setDatabase({
        uri: config.uri,
        username: config.username,
        password: config.password,
        database: config.database,
      });
      setStatus(config.connected ? "success" : "error");
      setNeo4jConnected(config.connected);
      if (config.connected) {
        toast.success("Neo4j connected");
      } else {
        setErrorMsg("Connection failed");
        toast.error("Neo4j connection failed");
      }
    } catch (error) {
      setStatus("error");
      const msg =
        error instanceof Error
          ? error.message
          : "Network error — is the backend running?";
      setErrorMsg(msg);
      toast.error(msg);
      setNeo4jConnected(false);
    }
  }, [database, setDatabase, setNeo4jConnected]);

  return (
    <div className="space-y-8">
      {/* ── Connection status banner ─────────────────────────────── */}
      <div
        className={cn(
          "flex items-center gap-3 rounded-xl border-2 p-4",
          status === "success"
            ? "border-success/30 bg-success-bg"
            : status === "error"
              ? "border-destructive/30 bg-destructive/5"
              : "border-border bg-muted/30"
        )}
      >
        {status === "success" ? (
          <CheckCircle2 className="h-5 w-5 text-success shrink-0" />
        ) : status === "error" ? (
          <XCircle className="h-5 w-5 text-destructive shrink-0" />
        ) : status === "testing" ? (
          <Loader2 className="h-5 w-5 text-muted-foreground animate-spin shrink-0" />
        ) : (
          <Circle className="h-5 w-5 text-muted-foreground shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {status === "success"
              ? "Connected to Neo4j"
              : status === "error"
                ? "Connection failed"
                : status === "testing"
                  ? "Testing connection..."
                  : "Not connected"}
          </p>
          {status === "success" && (
            <p className="text-2xs text-muted-foreground mt-0.5">{database.uri}</p>
          )}
          {status === "error" && errorMsg && (
            <p className="text-2xs text-destructive mt-0.5">{errorMsg}</p>
          )}
        </div>
      </div>

      {/* ── Connection settings ───────────────────────────────────── */}
      <div className="space-y-4">
        <div>
          <h3 className="text-[14px] font-semibold">Connection</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Configure the Neo4j database connection for the knowledge graph.
          </p>
        </div>

        <div className="space-y-3">
          <FormField label="URI" htmlFor="neo4j-uri">
            <Input
              id="neo4j-uri"
              value={database.uri}
              onChange={(e) => setDatabase({ uri: e.target.value })}
              placeholder="bolt://localhost:7687"
              className="h-8 text-sm"
            />
          </FormField>

          <div className="grid grid-cols-2 gap-3">
            <FormField label="Username" htmlFor="neo4j-user">
              <Input
                id="neo4j-user"
                value={database.username}
                onChange={(e) => setDatabase({ username: e.target.value })}
                placeholder="neo4j"
                className="h-8 text-sm"
              />
            </FormField>

            <FormField label="Password" htmlFor="neo4j-pass">
              <div className="relative">
                <Input
                  id="neo4j-pass"
                  type={showPassword ? "text" : "password"}
                  value={database.password}
                  onChange={(e) => setDatabase({ password: e.target.value })}
                  placeholder="••••••••"
                  className="h-8 text-sm pr-9"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground transition-colors"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? (
                    <EyeOff className="h-3.5 w-3.5" />
                  ) : (
                    <Eye className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            </FormField>
          </div>

          <FormField label="Database" htmlFor="neo4j-database">
            <Input
              id="neo4j-database"
              value={database.database}
              onChange={(e) => setDatabase({ database: e.target.value })}
              placeholder="neo4j"
              className="h-8 text-sm"
            />
          </FormField>
        </div>

        <Button
          onClick={testConnection}
          disabled={status === "testing"}
          size="sm"
        >
          {status === "testing" && (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          )}
          Test Connection
        </Button>
      </div>
    </div>
  );
}
