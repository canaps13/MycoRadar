FROM node:24-trixie-slim@sha256:54f84b4cf8432b21aaffd5d3ce8d41e12cea0d10d33c09d2f3c9879d49d6b446
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then \
      NODE_EXTRA_CA_CERTS=/run/secrets/build_ca npm ci; \
    else npm ci; fi
COPY . .
RUN npm run build
RUN chown -R node:node /app
USER node
EXPOSE 5173
CMD ["npm", "exec", "--", "vite", "preview", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
