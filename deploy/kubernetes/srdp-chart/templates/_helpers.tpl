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
Init container that blocks pod start until the DuckLake bucket answers to this
pod's own S3 key, the S3 counterpart of wait-for-ducklake-db. The bucket may
only appear once the srdp-setup hook Job's Garage step has run. Checking with
the pod's own key needs no extra rights, and a wrong key shows up as a pod
stuck in Init instead of a failing query. With local storage it exits at once.
Usage: {{ include "srdp.waitForDucklakeBucket" "srdp-ducklake-s3-reader" }}
The Dagster code location has the same container in values.yaml, with the
writer Secret; keep the two in step.
*/}}
{{- define "srdp.waitForDucklakeBucket" -}}
- name: wait-for-ducklake-bucket
  image: curlimages/curl:8.22.0
  envFrom:
    {{- include "srdp.ducklakeEnvFrom" . | nindent 4 }}
  env:
    {{- include "srdp.ducklakeS3Key" . | nindent 4 }}
  command:
    - sh
    - -c
    - |
      if [ "$DUCKLAKE_STORAGE_BACKEND" != "s3" ]; then exit 0; fi
      scheme=https
      if [ "$DUCKLAKE_S3_USE_SSL" = "false" ]; then scheme=http; fi
      url="$scheme://$DUCKLAKE_S3_ENDPOINT/$DUCKLAKE_S3_BUCKET"
      for i in $(seq 1 60); do
        # The key goes in through stdin, so it never shows in the process list.
        code=$(printf 'user = "%s:%s"\n' "$DUCKLAKE_S3_KEY_ID" "$DUCKLAKE_S3_SECRET" |
          curl -s -o /dev/null -w '%{http_code}' -K - --aws-sigv4 "aws:amz:$DUCKLAKE_S3_REGION:s3" -I "$url")
        if [ "$code" = "200" ]; then exit 0; fi
        echo "waiting for bucket $DUCKLAKE_S3_BUCKET at $DUCKLAKE_S3_ENDPOINT, HTTP $code ($i/60)..."
        sleep 2
      done
      echo "bucket $DUCKLAKE_S3_BUCKET still unreachable with this pod's key after 60 attempts, giving up." >&2
      exit 1
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
{{ include "srdp.ducklakeS3Key" "srdp-ducklake-s3-reader" }}
{{- end -}}

{{/*
DUCKLAKE_S3_KEY_ID and DUCKLAKE_S3_SECRET from the given role Secret. The
apps pass srdp-ducklake-s3-reader: a SQL console runs with the full authority
of its S3 key, so only Dagster gets the writer key (values.yaml). Optional, so
local storage needs no such Secret.
*/}}
{{- define "srdp.ducklakeS3Key" -}}
- name: DUCKLAKE_S3_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ . }}
      key: DUCKLAKE_S3_KEY_ID
      optional: true
- name: DUCKLAKE_S3_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ . }}
      key: DUCKLAKE_S3_SECRET
      optional: true
{{- end -}}

{{/*
DUCKLAKE_STORAGE_BACKEND and the S3 settings, one source for every consumer.
*/}}
{{- define "srdp.ducklakeEnvFrom" -}}
- configMapRef:
    name: srdp-ducklake-storage
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
