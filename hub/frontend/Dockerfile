# Hub Admin Frontend — Next.js 14 (dev mode, hot reload)
FROM node:20-alpine

WORKDIR /app

# Install deps first for better layer caching
COPY package.json package-lock.json* ./
RUN npm install

# Source mounted as volume in dev — but copy for prod build fallback
COPY . .

EXPOSE 3000

# Dev mode (hot reload). For production use `next build && next start`
CMD ["npm", "run", "dev"]
