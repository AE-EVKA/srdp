{{/*
Blocks pod start until <user> can log in to <db>. Logging in with the
consumer's own password also waits out a password change the setup hook
hasn't applied yet. Literal copies live in values*.yaml, keep them in step.
*/}}
{{- define "srdp.waitForDbLogin" -}}
- name: wait-for-{{ .db }}-db
  image: postgres:17-alpine
  command:
    - sh
    - -c
    - |
      for i in $(seq 1 60); do
        psql -tAc "SELECT 1" >/dev/null && exit 0
        echo "waiting for $PGUSER to log in to $PGDATABASE ($i/60)..."
        sleep 2
      done
      exit 1
  securityContext:
    runAsNonRoot: true
    runAsUser: 70
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: [ALL]
  env:
    - name: PGHOST
      value: {{ .root.Values.global.postgresqlHost | quote }}
    - name: PGUSER
      value: {{ .user | quote }}
    - name: PGDATABASE
      value: {{ .db | quote }}
    - name: PGPASSWORD
      {{- if .secretName }}
      valueFrom:
        secretKeyRef:
          name: {{ .secretName }}
          key: {{ .secretKey }}
      {{- else }}
      value: {{ .password | quote }}
      {{- end }}
{{- end -}}

{{/*
DuckLake connects as the superuser, see DUCKLAKE_PG_* in api.yaml and duckdb-ui.yaml.
*/}}
{{- define "srdp.waitForDucklakeDb" -}}
{{ include "srdp.waitForDbLogin" (dict "root" . "db" "ducklake" "user" "postgres" "secretName" "db-postgresql" "secretKey" "postgres-password") }}
{{- end -}}
