/**
 * 认证契约（Zod 镜像）。
 *
 * Mirror of `backend/app/contracts/auth.py`。字段名与形态必须与 Pydantic 侧字节级一致。
 * conformance gate（`pnpm contracts:check` + `backend/tests/test_contracts_parity.py`）强制校验。
 * 设计依据：§17.3 注册审核流转、§17.3.3 JWT + Refresh Token。
 */

import { z } from "zod";

/** 学生自助注册请求。注册即 PENDING，待管理员审核。 */
export const RegisterRequest = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(72),
  student_no: z.string().max(64).optional(),
});
export type RegisterRequest = z.infer<typeof RegisterRequest>;

/** 注册成功响应。status 恒为 PENDING。 */
export const RegisterResponse = z.object({
  user_id: z.string().min(1),
  email: z.string().email(),
  status: z.literal("PENDING"),
  message: z.string().min(1),
});
export type RegisterResponse = z.infer<typeof RegisterResponse>;

/** 登录请求（学生/管理员通用）。 */
export const LoginRequest = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});
export type LoginRequest = z.infer<typeof LoginRequest>;

/** 令牌对。access_token 短期，refresh_token 长期。 */
export const AuthTokens = z.object({
  access_token: z.string().min(1),
  refresh_token: z.string().min(1),
  token_type: z.literal("Bearer"),
  expires_in: z.number().int().positive(),
});
export type AuthTokens = z.infer<typeof AuthTokens>;

/** 刷新令牌请求。 */
export const TokenRefreshRequest = z.object({
  refresh_token: z.string().min(1),
});
export type TokenRefreshRequest = z.infer<typeof TokenRefreshRequest>;

/** 当前用户信息。不含密码哈希。 */
export const UserProfile = z.object({
  id: z.string().min(1),
  email: z.string().email(),
  tenant_id: z.string().min(1),
  roles: z.array(z.string()).default([]),
  status: z.string().min(1),
  display_name: z.string().optional(),
});
export type UserProfile = z.infer<typeof UserProfile>;

/** 待审核注册条目（管理端列表用）。 */
export const PendingRegistration = z.object({
  user_id: z.string().min(1),
  email: z.string().email(),
  student_no: z.string().optional(),
  status: z.string().min(1),
  created_at: z.string().min(1),
});
export type PendingRegistration = z.infer<typeof PendingRegistration>;

/** 管理员审核决定（批准/拒绝）。 */
export const RegistrationDecisionRequest = z.object({
  reason: z.string().max(500).optional(),
});
export type RegistrationDecisionRequest = z.infer<typeof RegistrationDecisionRequest>;
