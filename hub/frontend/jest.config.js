// Jest config สำหรับ frontend (Next.js 14 + React Testing Library)
// ใช้ next/jest เพื่อ transform TS/JSX + alias @/* ให้ตรงกับ tsconfig
const nextJest = require("next/jest");

const createJestConfig = nextJest({ dir: "./" });

/** @type {import('jest').Config} */
const config = {
  testEnvironment: "jest-environment-jsdom",
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
  },
  testMatch: [
    "<rootDir>/**/__tests__/**/*.test.{ts,tsx}",
    "<rootDir>/**/*.test.{ts,tsx}",
  ],
  testPathIgnorePatterns: ["/node_modules/", "/.next/"],
};

module.exports = createJestConfig(config);
