"use client";

import { useEffect, useState } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import "leaflet/dist/leaflet.css";

type Camera = { id: string; name: string; latitude: number | null; longitude: number | null };

function FitCameras({ cameras }: { cameras: Camera[] }) {
  const map = useMap();
  useEffect(() => {
    const locations = cameras.filter((camera) => camera.latitude !== null && camera.longitude !== null);
    if (locations.length) {
      const bounds = locations.map((camera) => [camera.latitude!, camera.longitude!] as [number, number]) as LatLngBoundsExpression;
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
    }
  }, [cameras, map]);
  return null;
}

export default function MapView({ cameras }: { cameras: Camera[] }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const located = cameras.filter((camera) => camera.latitude !== null && camera.longitude !== null);
  if (!mounted) return <div className="h-full min-h-[390px] animate-pulse rounded-xl bg-slate-800/40" />;
  return (
    <div className="map-shell h-full min-h-[390px] overflow-hidden rounded-xl">
      <MapContainer center={[20, 0]} zoom={2} scrollWheelZoom className="h-full min-h-[390px]">
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <FitCameras cameras={located} />
        {located.map((camera) => <CircleMarker key={camera.id} center={[camera.latitude!, camera.longitude!]} radius={7} pathOptions={{ color: "#00e5ff", fillColor: "#00e5ff", fillOpacity: .8, weight: 2 }}>
          <Tooltip>{camera.name}</Tooltip>
        </CircleMarker>)}
      </MapContainer>
    </div>
  );
}
