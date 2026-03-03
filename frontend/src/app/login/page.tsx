import Link from "next/link";
import { AuthForm } from "@/components/AuthForm";

export default function LoginPage() {
  return (
    <div className="max-w-sm mx-auto px-6 py-16">
      <h1 className="text-2xl font-bold text-teal mb-8">Sign in</h1>
      <AuthForm mode="login" />
      <p className="mt-6 text-sm text-dark-light">
        Don&apos;t have an account?{" "}
        <Link href="/register" className="text-copper hover:underline">
          Create one
        </Link>
      </p>
    </div>
  );
}
