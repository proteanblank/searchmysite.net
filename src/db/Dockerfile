FROM postgres:17.5-alpine
# Note: A data export and import will be required to upgrade major versions of postgres

# scripts in /docker-entrypoint-initdb.d are only run if you start the container with a data directory that is empty; 
# any pre-existing database will be left untouched on container startup

ADD sql/* /docker-entrypoint-initdb.d/

# Dev docker-compose.yml has the following:
#    volumes:
#      - "../data/sqldata:/var/lib/postgresql/data"
# No need to copy this in to the prod image though

