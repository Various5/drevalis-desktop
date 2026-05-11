FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY public /usr/share/nginx/html

# nginx workers run as the unprivileged ``nginx`` user; make sure every
# copied file/dir is at least world-readable/traversable regardless of the
# host's umask.
RUN chmod -R a+rX /usr/share/nginx/html

EXPOSE 80
