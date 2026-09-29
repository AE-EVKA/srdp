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
          name: db-postgresql
          key: postgres-password
{{- end -}}
