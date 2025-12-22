"use client"

import { CirclePlus, Mail, type LucideIcon } from "lucide-react"
import { useLocation } from "react-router-dom"
import { NavLink } from "react-router-dom"
import { Button } from "@/components/UI/button"
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/UI/sidebar"

interface NavMainItem {
  title: string
  url: string
  icon?: LucideIcon
}

export function NavMain({
  items,
}: {
  items: NavMainItem[]
}) {
  const location = useLocation()
  
  return (
    <SidebarGroup>
      <SidebarGroupContent className="flex flex-col gap-2">
        <SidebarMenu>
          <SidebarMenuItem className="flex items-center gap-2">
            <SidebarMenuButton
              tooltip="Быстрое создание"
              className="bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground active:bg-primary/90 active:text-primary-foreground min-w-8 duration-200 ease-linear"
              asChild
              isActive={location.pathname === "/cases/new"}
            >
              <NavLink to="/cases/new">
                <CirclePlus />
                <span>Быстрое создание</span>
              </NavLink>
            </SidebarMenuButton>
            <Button
              size="icon"
              className="size-8 group-data-[collapsible=icon]:opacity-0"
              variant="outline"
              asChild
            >
              <NavLink to="/cases">
                <Mail />
                <span className="sr-only">Дела</span>
              </NavLink>
            </Button>
          </SidebarMenuItem>
        </SidebarMenu>
        <SidebarMenu>
          {items.map((item) => {
            const isActive = location.pathname === item.url || location.pathname.startsWith(item.url + '/')
            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton tooltip={item.title} asChild isActive={isActive}>
                  <NavLink to={item.url}>
                    {item.icon && <item.icon />}
                    <span>{item.title}</span>
                  </NavLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

