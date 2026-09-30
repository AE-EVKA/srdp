{{/*
Init container that blocks pod start until the ducklake database exists,
checked directly rather than relying on Deployment ordering against the
srdp-setup post-install/post-upgrade hook, which has no ordering guarantee
against the chart's regular Deployments. See templates/marquez.yaml's
wait-for-marquez-db initContainer for the same reasoning.
*/}}
{{- define "srdp.waitForDucklakeDb" -}}
- name: wait-for-ducklake-db
  image: postgres:17-alpine
  command:
    - sh
    - -c
    - |
      for i in $(seq 1 30); do
        if psql "postgresql://postgres@{{ .Values.global.postgresqlHost }}:5432/postgres" -tAc \
          "SELECT 1 FROM pg_database WHERE datname = 'ducklake'" | grep -q 1; then
          exit 0
        fi
        echo "waiting for the ducklake database to be created ($i/30)..."
        sleep 2
      done
      echo "ducklake database still missing after 30 attempts, giving up." >&2
      exit 1
  env:
    - name: PGPASSWORD
      valueFrom:
        secretKeyRef:
          name: srdp-postgres
          key: postgres-password
{{- end -}}

{{/*
DuckLake connection env for the apps that read the catalog, the Kubernetes
equivalent of the DUCKLAKE_* block on each app in docker-compose.yml.
*/}}
{{- define "srdp.ducklakeEnv" -}}
- name: DUCKLAKE_PG_HOST
  value: {{ .Values.global.postgresqlHost | quote }}
- name: DUCKLAKE_PG_USER
  value: postgres
- name: DUCKLAKE_PG_PASSWORD
  valueFrom:
    secretKeyRef:
      name: srdp-postgres
      key: postgres-password
- name: DUCKLAKE_PG_DB
  value: ducklake
- name: DUCKLAKE_DATA_PATH
  value: {{ .Values.ducklakeData.mountPath | quote }}
{{- end -}}

{{/*
Read-only mount of the shared DuckLake data volume (templates/ducklake-data-pvc.yaml),
same as the ducklake-data:/data/ducklake:ro mount of the Compose readers.
*/}}
{{- define "srdp.ducklakeVolumeMount" -}}
- name: ducklake-data
  mountPath: {{ .Values.ducklakeData.mountPath | quote }}
  readOnly: true
{{- end -}}

{{- define "srdp.ducklakeVolume" -}}
- name: ducklake-data
  persistentVolumeClaim:
    claimName: ducklake-data
{{- end -}}

{{/*
Image reference for an image this repo builds, prefixed with
global.srdpRegistry so one value moves every SRDP image to another registry.
Usage: {{ include "srdp.image" (list . .Values.api.image) }}
*/}}
{{- define "srdp.image" -}}
{{- $root := index . 0 -}}
{{- $image := index . 1 -}}
{{- printf "%s/%s:%s" (trimSuffix "/" $root.Values.global.srdpRegistry) $image.repository $image.tag | quote -}}
{{- end -}}

{{/*
Pod-level imagePullSecrets from global.imagePullSecrets, empty when unset.
*/}}
{{- define "srdp.imagePullSecrets" -}}
{{- with .Values.global.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}
