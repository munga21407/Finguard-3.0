export function AuthBackground() {
  return (
    <>
      {/* Dot pattern */}
      <div
        className="absolute inset-0 pointer-events-none opacity-40"
        style={{
          backgroundColor: "#f8f9fa",
          backgroundImage:
            "radial-gradient(#d0bcff 0.5px, transparent 0.5px), radial-gradient(#d0bcff 0.5px, #f8f9fa 0.5px)",
          backgroundSize: "20px 20px",
          backgroundPosition: "0 0, 10px 10px",
        }}
      />
      {/* Top-right blob */}
      <div className="absolute top-[-10%] right-[-10%] w-[40%] h-[40%] bg-lf-primary-fixed/30 blur-[120px] rounded-full pointer-events-none" />
      {/* Bottom-left blob */}
      <div className="absolute bottom-[-10%] left-[-10%] w-[40%] h-[40%] bg-lf-secondary-fixed/30 blur-[120px] rounded-full pointer-events-none" />
    </>
  );
}
