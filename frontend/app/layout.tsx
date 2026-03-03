import type { Metadata } from 'next'
import Nav from '@/components/Nav'
import './globals.css'

export const metadata: Metadata = {
  title: 'Eisla — Customer Portal',
  description: 'Manage your PCB projects — from words to boards.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-cream font-sans text-near-black">
        <Nav />
        <main className="ml-60 min-h-screen">{children}</main>
      </body>
    </html>
  )
}
