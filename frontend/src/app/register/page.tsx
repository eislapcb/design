import Link from "next/link";
import { AuthForm } from "@/components/AuthForm";

export default function RegisterPage() {
  return (
    <div className="max-w-sm mx-auto px-6 py-16">
      <h1 className="text-2xl font-bold text-teal mb-8">Create your account</h1>
      <AuthForm mode="register" />
      <p className="mt-6 text-sm text-dark-light">
        Already have an account?{" "}
        <Link href="/login" className="text-copper hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
