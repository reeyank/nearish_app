import { Hono } from "hono";
import { serve } from "@hono/node-server";
import { betterAuth } from "better-auth";
import { Pool } from "pg";
import { anonymous } from "better-auth/plugins";
import { expo } from "@better-auth/expo";
import { cors } from "hono/cors";
import { getMigrations } from "better-auth/db";
import "dotenv/config";

// Initialize shared database
const db = new Pool({
  connectionString: process.env.DATABASE_URL,
});

// Configure Better Auth
export const auth = betterAuth({
  database: db,
  plugins: [
    anonymous({
        onLinkAccount: async ({ anonymousUser, newUser }) => {
            console.log(`[LINK] ${anonymousUser.user.id} -> ${newUser.user.id}`);
            try {
                await db.query(
                    'UPDATE nearish_user SET "better_auth_id" = $1 WHERE "better_auth_id" = $2',
                    [newUser.user.id, anonymousUser.user.id]
                );
                console.log("[LINK] Success: Updated better_auth_id pointer.");
            } catch (err: any) {
                if (err.code === '23505') {
                    console.log("[LINK] Conflict: Target already has profile. Cleaning up anonymous data.");
                    try {
                        const res = await db.query('SELECT id FROM nearish_user WHERE "better_auth_id" = $1', [anonymousUser.user.id]);
                        if (res.rows.length > 0) {
                            const stableId = res.rows[0].id;
                            await db.query('DELETE FROM streak WHERE "nearish_user_id" = $1', [stableId]);
                            await db.query('DELETE FROM nearish_user WHERE id = $1', [stableId]);
                        }
                    } catch (cleanupErr) { console.error("[LINK] Cleanup failed", cleanupErr); }
                } else {
                    console.error("[LINK] Error:", err);
                }
            }
        }
    }),
    expo(),      // Enable Expo support
  ],
  emailAndPassword: {
    enabled: true, // Keep standard email/pass enabled if needed later
  },
  trustedOrigins: [
    "exp://*",
    "ldr://*",
    "nearish://*",
    "http://localhost:8081",
    "http://localhost:8082"
  ],
  advanced: {
      disableOriginCheck: true
  }
});

const app = new Hono();

// Enable CORS
app.use("*", cors({
  origin: (origin) => origin, // Allow all origins for dev simplicity, restrict in prod
  credentials: true,
  allowMethods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
  allowHeaders: ["Content-Type", "Authorization", "Cookie"],
}));

// Mount Better Auth handler
app.on(["POST", "GET"], "/api/auth/*", (c) => {
  return auth.handler(c.req.raw);
});

console.log("Auth Server running on http://localhost:4000");

// Run Migrations & Start Server
getMigrations(auth.options).then(async ({ runMigrations }) => {
    await runMigrations();
    console.log("Database migrations ran successfully.");
    
    serve({
      fetch: app.fetch,
      port: 4000,
    });
}).catch(err => {
    console.error("Failed to run migrations:", err);
    process.exit(1);
});
