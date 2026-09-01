# SAMAN frontend — Vite dev server (prototype; `npm run build` for production)
FROM node:22-slim

WORKDIR /srv/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
