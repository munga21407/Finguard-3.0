"use client";

import { useEffect, useState } from "react";
import { ENDPOINTS } from "@/lib/api/endpoints";
import httpClient from "@/lib/api/http-client";

type Product = {
  id: string;
  sku: string;
  name: string;
  category?: string | null;
  cost_price: string;
  selling_price: string;
  reorder_level: string;
  reorder_quantity: string;
};

export default function InventoryPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await httpClient.get(ENDPOINTS.INVENTORY.PRODUCTS);
        setProducts(res.data as Product[]);
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Stock Management</h1>
          <p className="text-sm text-gray-500">Track inventory levels, movement history, and reorder alerts.</p>
        </div>
      </div>

      {loading ? (
        <p>Loading inventory…</p>
      ) : (
        <div className="grid gap-4">
          {products.map((product) => (
            <div key={product.id} className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-medium">{product.name}</div>
                  <div className="text-sm text-gray-500">SKU: {product.sku}</div>
                </div>
                <div className="text-right text-sm">
                  <div>Cost: {product.cost_price}</div>
                  <div>Sell: {product.selling_price}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
