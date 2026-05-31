import { RegisterForm } from "@/components/forms/RegisterForm";

export default function RegisterPage() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-md">
        <h1 className="text-3xl font-bold text-center text-brand-700 mb-8">Finguard</h1>
        <RegisterForm />
      </div>
    </main>
  );
}
